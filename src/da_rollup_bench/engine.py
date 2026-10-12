"""Deterministic single-threaded discrete-event simulation engine.

Event ordering is ``(timestamp, priority, monotonic sequence)``. At equal times:
service completions and confirmations run first, then Ethereum block slots, batch
timeouts, arrivals, retry-ready/enqueue events, and finally the horizon event.
Consequently a batch created exactly on a block boundary waits for the next slot,
and a transaction arriving exactly at its active batch deadline starts a new batch.
"""

from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Any

from .batching import StatefulBatcher
from .config import (
    BatchingConfig,
    EthereumConfig,
    ExternalDAConfig,
    SimulationConfig,
    TerminationPolicy,
)
from .da.base import DAPublicationStrategy, PreparedPublication
from .da.external_mock import MockExternalDAStrategy
from .domain import Batch, Transaction
from .workload import workload_fingerprint


class EventPriority(IntEnum):
    SERVICE_COMPLETE = 0
    CONFIRMATION_COMPLETE = 1
    BLOCK_SLOT = 2
    BATCH_TIMEOUT = 3
    TRANSACTION_ARRIVAL = 4
    RETRY_READY = 5
    PUBLICATION_ENQUEUE = 6
    HORIZON = 99


class EntityState(StrEnum):
    GENERATED = "generated"
    BUFFERED = "buffered"
    BATCHED = "batched"
    QUEUED = "queued"
    SERVING = "serving"
    RETRY_WAIT = "retry_wait"
    PUBLISHED = "published"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    UNFINISHED = "unfinished"


@dataclass(order=True, frozen=True, slots=True)
class _Event:
    timestamp: float
    priority: int
    sequence: int
    kind: str = field(compare=False)
    payload: Any = field(compare=False)


@dataclass(frozen=True, slots=True)
class StateTransition:
    timestamp: float
    entity_type: str
    entity_id: str
    old_state: str
    new_state: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationAttempt:
    attempt_number: int
    enqueue_time: float
    service_start_time: float
    service_end_time: float | None
    succeeded: bool | None
    cost: Decimal
    cost_unit: str

    @property
    def queue_latency(self) -> float:
        return self.service_start_time - self.enqueue_time

    @property
    def service_latency(self) -> float:
        if self.service_end_time is None:
            return 0.0
        return self.service_end_time - self.service_start_time


@dataclass(frozen=True, slots=True)
class PublicationOutcome:
    publication_id: str
    batch_id: str
    state: EntityState
    prepared: PreparedPublication
    attempts: tuple[PublicationAttempt, ...]
    confirmation_time: float | None
    retry_backoff_seconds: float
    rejection_reason: str | None

    @property
    def total_cost(self) -> Decimal:
        return sum((attempt.cost for attempt in self.attempts), Decimal(0))

    @property
    def cumulative_queue_latency(self) -> float:
        return sum(attempt.queue_latency for attempt in self.attempts)

    @property
    def cumulative_service_latency(self) -> float:
        return sum(attempt.service_latency for attempt in self.attempts)


@dataclass(frozen=True, slots=True)
class TransactionOutcome:
    tx_id: str
    state: EntityState
    arrival_time: float
    batch_id: str | None
    completion_time: float | None
    rejection_reason: str | None
    batching_latency: float | None
    queue_latency: float
    service_latency: float
    retry_backoff_latency: float
    confirmation_latency: float

    @property
    def end_to_end_latency(self) -> float | None:
        if self.completion_time is None:
            return None
        return self.completion_time - self.arrival_time

    @property
    def latency_component_sum(self) -> float | None:
        if self.batching_latency is None:
            return None
        return (
            self.batching_latency
            + self.queue_latency
            + self.service_latency
            + self.retry_backoff_latency
            + self.confirmation_latency
        )


@dataclass(frozen=True, slots=True)
class ResourceAccounting:
    observation_end_time: float
    maximum_queue_depth: int
    time_weighted_queue_depth: float
    external_busy_server_seconds: float
    external_service_concurrency: int | None
    external_maximum_active_services: int
    ethereum_slots_processed: int
    ethereum_consumed_gas: int
    ethereum_available_gas_budget: int
    ethereum_slot_gas: tuple[tuple[float, int], ...]


@dataclass(frozen=True, slots=True)
class SimulationResult:
    strategy_id: str
    measurement_horizon_seconds: float
    termination_policy: TerminationPolicy
    run_end_time: float
    workload_fingerprint: str
    batches: tuple[Batch, ...]
    transactions: tuple[TransactionOutcome, ...]
    publications: tuple[PublicationOutcome, ...]
    transitions: tuple[StateTransition, ...]
    resource: ResourceAccounting


@dataclass(slots=True)
class _MutableTransaction:
    transaction: Transaction
    state: EntityState = EntityState.GENERATED
    batch_id: str | None = None
    completion_time: float | None = None
    rejection_reason: str | None = None
    batching_latency: float | None = None
    queue_latency: float = 0.0
    service_latency: float = 0.0
    retry_backoff_latency: float = 0.0
    confirmation_latency: float = 0.0


@dataclass(slots=True)
class _MutablePublication:
    batch: Batch
    prepared: PreparedPublication
    state: EntityState = EntityState.BATCHED
    attempts: list[PublicationAttempt] = field(default_factory=list)
    confirmation_time: float | None = None
    retry_backoff_seconds: float = 0.0
    rejection_reason: str | None = None


class SimulationEngine:
    """Run one strategy against one fixed transaction workload."""

    def __init__(
        self,
        *,
        batching: BatchingConfig,
        strategy: DAPublicationStrategy,
        ethereum: EthereumConfig,
        external_da: ExternalDAConfig,
        simulation: SimulationConfig,
    ) -> None:
        self.batching_config = batching
        self.strategy = strategy
        self.ethereum = ethereum
        self.external_da = external_da
        self.simulation = simulation
        self._is_external = isinstance(strategy, MockExternalDAStrategy)
        self._events: list[_Event] = []
        self._sequence = 0
        self._processed_events = 0
        self._batcher = StatefulBatcher(batching)
        self._batches: list[Batch] = []
        self._tx: dict[str, _MutableTransaction] = {}
        self._pub: dict[str, _MutablePublication] = {}
        self._transitions: list[StateTransition] = []
        self._ethereum_queue: deque[str] = deque()
        self._block_slot_scheduled = False
        self._external_queue: deque[tuple[str, int, float]] = deque()
        self._external_active = 0
        self._external_max_active = 0
        self._queue_depth = 0
        self._queue_last_time = 0.0
        self._queue_area = 0.0
        self._max_queue_depth = 0
        self._external_busy_seconds = 0.0
        self._external_active_started: dict[tuple[str, int], float] = {}
        self._eth_slots = 0
        self._eth_consumed = 0
        self._eth_slot_gas: list[tuple[float, int]] = []
        self._meaningful_end = 0.0

    def _schedule(self, timestamp: float, priority: EventPriority, kind: str, payload: Any) -> None:
        if timestamp < 0 or not math.isfinite(timestamp):
            raise ValueError("event time must be finite and non-negative")
        event = _Event(timestamp, int(priority), self._sequence, kind, payload)
        self._sequence += 1
        heapq.heappush(self._events, event)

    def _transition(
        self,
        entity_type: str,
        entity_id: str,
        old: EntityState,
        new: EntityState,
        now: float,
        reason: str | None = None,
    ) -> None:
        self._transitions.append(
            StateTransition(now, entity_type, entity_id, old.value, new.value, reason)
        )
        self._meaningful_end = max(self._meaningful_end, now)

    def _set_transaction_state(
        self, tx_id: str, new: EntityState, now: float, reason: str | None = None
    ) -> None:
        record = self._tx[tx_id]
        old = record.state
        record.state = new
        self._transition("transaction", tx_id, old, new, now, reason)

    def _set_publication_state(
        self, publication_id: str, new: EntityState, now: float, reason: str | None = None
    ) -> None:
        record = self._pub[publication_id]
        old = record.state
        record.state = new
        self._transition("publication", publication_id, old, new, now, reason)

    def _update_queue_depth(self, now: float, new_depth: int) -> None:
        self._queue_area += self._queue_depth * (now - self._queue_last_time)
        self._queue_last_time = now
        self._queue_depth = new_depth
        self._max_queue_depth = max(self._max_queue_depth, new_depth)

    def _schedule_batch_timer(self, timer: tuple[int, float] | None) -> None:
        if timer is not None:
            generation, deadline = timer
            self._schedule(deadline, EventPriority.BATCH_TIMEOUT, "batch_timeout", generation)

    def _close_batch(self, batch: Batch) -> None:
        self._batches.append(batch)
        for transaction in batch.transactions:
            record = self._tx[transaction.tx_id]
            record.batch_id = batch.batch_id
            record.batching_latency = batch.closed_at - transaction.arrival_time
            self._set_transaction_state(transaction.tx_id, EntityState.BATCHED, batch.closed_at)
        publication_id = batch.batch_id
        prepared = self.strategy.prepare(publication_id, batch.raw_payload)
        self._pub[publication_id] = _MutablePublication(batch=batch, prepared=prepared)
        self._schedule(
            batch.closed_at,
            EventPriority.PUBLICATION_ENQUEUE,
            "publication_enqueue",
            publication_id,
        )

    def _reject_publication(self, publication_id: str, now: float, reason: str) -> None:
        publication = self._pub[publication_id]
        publication.rejection_reason = reason
        self._set_publication_state(publication_id, EntityState.REJECTED, now, reason)
        for transaction in publication.batch.transactions:
            record = self._tx[transaction.tx_id]
            record.rejection_reason = reason
            self._set_transaction_state(transaction.tx_id, EntityState.REJECTED, now, reason)

    def _next_block_slot(self, now: float) -> float:
        interval = self.ethereum.block_interval_seconds
        return (math.floor(now / interval) + 1) * interval

    def _ensure_block_slot(self, now: float) -> None:
        if not self._block_slot_scheduled:
            self._block_slot_scheduled = True
            self._schedule(
                self._next_block_slot(now), EventPriority.BLOCK_SLOT, "block_slot", None
            )

    def _enqueue_ethereum(self, publication_id: str, now: float) -> None:
        publication = self._pub[publication_id]
        demand = publication.prepared.capacity_demand
        if demand > self.ethereum.da_gas_budget_per_block:
            self._reject_publication(publication_id, now, "exceeds_block_gas_budget")
            return
        if len(self._ethereum_queue) >= self.ethereum.queue_capacity_requests:
            self._reject_publication(publication_id, now, "ethereum_queue_full")
            return
        self._ethereum_queue.append(publication_id)
        self._update_queue_depth(now, len(self._ethereum_queue))
        self._set_publication_state(publication_id, EntityState.QUEUED, now)
        for transaction in publication.batch.transactions:
            self._set_transaction_state(transaction.tx_id, EntityState.QUEUED, now)
        self._ensure_block_slot(now)

    def _ethereum_block_slot(self, now: float) -> None:
        self._block_slot_scheduled = False
        self._eth_slots += 1
        remaining = self.ethereum.da_gas_budget_per_block
        slot_consumed = 0
        while self._ethereum_queue:
            publication_id = self._ethereum_queue[0]
            publication = self._pub[publication_id]
            demand = publication.prepared.capacity_demand
            if demand > remaining:
                break
            self._ethereum_queue.popleft()
            self._update_queue_depth(now, len(self._ethereum_queue))
            remaining -= demand
            self._eth_consumed += demand
            slot_consumed += demand
            enqueue_time = publication.batch.closed_at
            attempt = PublicationAttempt(
                attempt_number=1,
                enqueue_time=enqueue_time,
                service_start_time=now,
                service_end_time=now,
                succeeded=True,
                cost=publication.prepared.monetary_cost,
                cost_unit=publication.prepared.monetary_cost_unit,
            )
            publication.attempts.append(attempt)
            self._set_publication_state(publication_id, EntityState.PUBLISHED, now)
            delay = self.simulation.ethereum_confirmation_delay_seconds
            self._schedule(
                now + delay,
                EventPriority.CONFIRMATION_COMPLETE,
                "confirmation_complete",
                publication_id,
            )
        self._eth_slot_gas.append((now, slot_consumed))
        if self._ethereum_queue:
            self._ensure_block_slot(now)

    def _start_external_attempt(
        self, publication_id: str, attempt_number: int, enqueue_time: float, now: float
    ) -> None:
        publication = self._pub[publication_id]
        service_time = publication.prepared.service_time_seconds
        if service_time is None:
            raise RuntimeError("external publication requires service_time_seconds")
        self._external_active += 1
        self._external_max_active = max(self._external_max_active, self._external_active)
        self._external_active_started[(publication_id, attempt_number)] = now
        publication.attempts.append(
            PublicationAttempt(
                attempt_number=attempt_number,
                enqueue_time=enqueue_time,
                service_start_time=now,
                service_end_time=None,
                succeeded=None,
                cost=publication.prepared.monetary_cost,
                cost_unit=publication.prepared.monetary_cost_unit,
            )
        )
        self._set_publication_state(publication_id, EntityState.SERVING, now)
        for transaction in publication.batch.transactions:
            self._set_transaction_state(transaction.tx_id, EntityState.SERVING, now)
        self._schedule(
            now + service_time,
            EventPriority.SERVICE_COMPLETE,
            "external_service_complete",
            (publication_id, attempt_number, enqueue_time, now),
        )

    def _admit_external(self, publication_id: str, attempt_number: int, now: float) -> None:
        publication = self._pub[publication_id]
        if not publication.prepared.admissible:
            self._reject_publication(
                publication_id,
                now,
                publication.prepared.rejection_reason or "inadmissible",
            )
            return
        if self._external_active < self.external_da.service_concurrency:
            self._start_external_attempt(publication_id, attempt_number, now, now)
            return
        if len(self._external_queue) >= self.external_da.queue_capacity_requests:
            self._reject_publication(publication_id, now, "external_queue_full")
            return
        self._external_queue.append((publication_id, attempt_number, now))
        self._update_queue_depth(now, len(self._external_queue))
        self._set_publication_state(publication_id, EntityState.QUEUED, now)
        for transaction in publication.batch.transactions:
            self._set_transaction_state(transaction.tx_id, EntityState.QUEUED, now)

    def _start_next_external_waiter(self, now: float) -> None:
        while (
            self._external_queue
            and self._external_active < self.external_da.service_concurrency
        ):
            publication_id, attempt_number, enqueue_time = self._external_queue.popleft()
            self._update_queue_depth(now, len(self._external_queue))
            self._start_external_attempt(publication_id, attempt_number, enqueue_time, now)

    def _external_service_complete(
        self, now: float, payload: tuple[str, int, float, float]
    ) -> None:
        publication_id, attempt_number, enqueue_time, service_start = payload
        publication = self._pub[publication_id]
        strategy = self.strategy
        if not isinstance(strategy, MockExternalDAStrategy):
            raise RuntimeError("external completion requires MockExternalDAStrategy")
        self._external_active -= 1
        started_at = self._external_active_started.pop((publication_id, attempt_number))
        self._external_busy_seconds += now - started_at
        succeeded = strategy.attempt_succeeds(publication_id, attempt_number)
        attempt_index = next(
            index
            for index, attempt in enumerate(publication.attempts)
            if attempt.attempt_number == attempt_number
        )
        publication.attempts[attempt_index] = replace(
            publication.attempts[attempt_index],
            service_end_time=now,
            succeeded=succeeded,
        )
        if succeeded:
            self._set_publication_state(publication_id, EntityState.PUBLISHED, now)
            self._schedule(
                now + self.simulation.external_confirmation_delay_seconds,
                EventPriority.CONFIRMATION_COMPLETE,
                "confirmation_complete",
                publication_id,
            )
        elif attempt_number <= self.external_da.max_retries:
            backoff = strategy.retry_backoff_seconds(attempt_number)
            publication.retry_backoff_seconds += backoff
            self._set_publication_state(publication_id, EntityState.RETRY_WAIT, now)
            for transaction in publication.batch.transactions:
                self._set_transaction_state(transaction.tx_id, EntityState.RETRY_WAIT, now)
            self._schedule(
                now + backoff,
                EventPriority.RETRY_READY,
                "retry_ready",
                (publication_id, attempt_number + 1),
            )
        else:
            self._set_publication_state(publication_id, EntityState.FAILED, now)
            for transaction in publication.batch.transactions:
                self._set_transaction_state(transaction.tx_id, EntityState.FAILED, now)
        self._start_next_external_waiter(now)

    def _confirmation_complete(self, publication_id: str, now: float) -> None:
        publication = self._pub[publication_id]
        publication.confirmation_time = now
        self._set_publication_state(publication_id, EntityState.COMPLETED, now)
        last_service_end = publication.attempts[-1].service_end_time
        if last_service_end is None:
            raise RuntimeError("cannot confirm an unfinished publication attempt")
        confirmation_latency = now - last_service_end
        for transaction in publication.batch.transactions:
            record = self._tx[transaction.tx_id]
            record.completion_time = now
            record.queue_latency = sum(attempt.queue_latency for attempt in publication.attempts)
            record.service_latency = sum(attempt.service_latency for attempt in publication.attempts)
            record.retry_backoff_latency = publication.retry_backoff_seconds
            record.confirmation_latency = confirmation_latency
            self._set_transaction_state(transaction.tx_id, EntityState.COMPLETED, now)

    def _handle(self, event: _Event) -> None:
        now = event.timestamp
        if event.kind == "transaction_arrival":
            transaction: Transaction = event.payload
            self._set_transaction_state(transaction.tx_id, EntityState.BUFFERED, now)
            batches, rejection, timer = self._batcher.on_transaction(transaction, now)
            if rejection is not None:
                record = self._tx[transaction.tx_id]
                record.rejection_reason = rejection.reason
                self._set_transaction_state(
                    transaction.tx_id, EntityState.REJECTED, now, rejection.reason
                )
            for batch in batches:
                self._close_batch(batch)
            self._schedule_batch_timer(timer)
        elif event.kind == "batch_timeout":
            batch = self._batcher.on_timeout(event.payload, now)
            if batch is not None:
                self._close_batch(batch)
        elif event.kind == "publication_enqueue":
            publication_id = event.payload
            publication = self._pub[publication_id]
            if not publication.prepared.admissible:
                self._reject_publication(
                    publication_id,
                    now,
                    publication.prepared.rejection_reason or "inadmissible",
                )
            elif self._is_external:
                self._admit_external(publication_id, 1, now)
            else:
                self._enqueue_ethereum(publication_id, now)
        elif event.kind == "block_slot":
            self._ethereum_block_slot(now)
        elif event.kind == "external_service_complete":
            self._external_service_complete(now, event.payload)
        elif event.kind == "retry_ready":
            publication_id, attempt_number = event.payload
            self._admit_external(publication_id, attempt_number, now)
        elif event.kind == "confirmation_complete":
            self._confirmation_complete(event.payload, now)
        elif event.kind == "horizon":
            batch = self._batcher.flush(now)
            if batch is not None:
                self._close_batch(batch)
        else:
            raise RuntimeError(f"unknown event kind: {event.kind}")

    def run(self, transactions: tuple[Transaction, ...]) -> SimulationResult:
        if len({transaction.tx_id for transaction in transactions}) != len(transactions):
            raise ValueError("transaction IDs must be unique")
        if any(
            right.arrival_time < left.arrival_time
            for left, right in zip(transactions, transactions[1:])
        ):
            raise ValueError("transactions must be ordered by arrival time")
        horizon = self.simulation.measurement_horizon_seconds
        if any(transaction.arrival_time >= horizon for transaction in transactions):
            raise ValueError("all transaction arrivals must be inside [0, measurement_horizon)")
        self._tx = {
            transaction.tx_id: _MutableTransaction(transaction) for transaction in transactions
        }
        for transaction in transactions:
            self._schedule(
                transaction.arrival_time,
                EventPriority.TRANSACTION_ARRIVAL,
                "transaction_arrival",
                transaction,
            )
        self._schedule(horizon, EventPriority.HORIZON, "horizon", None)

        while self._events:
            event = heapq.heappop(self._events)
            self._processed_events += 1
            if self._processed_events > self.simulation.max_events:
                raise RuntimeError("simulation exceeded max_events safety limit")
            self._handle(event)
            if (
                event.kind == "horizon"
                and self.simulation.termination_policy == TerminationPolicy.TRUNCATE
            ):
                break

        run_end = horizon if self.simulation.termination_policy == TerminationPolicy.TRUNCATE else max(
            horizon, self._meaningful_end
        )
        self._queue_area += self._queue_depth * (run_end - self._queue_last_time)
        for record in self._tx.values():
            if record.state not in {
                EntityState.COMPLETED,
                EntityState.REJECTED,
                EntityState.FAILED,
            }:
                self._set_transaction_state(record.transaction.tx_id, EntityState.UNFINISHED, run_end)
        for publication_id, publication in self._pub.items():
            if publication.state not in {
                EntityState.COMPLETED,
                EntityState.REJECTED,
                EntityState.FAILED,
            }:
                self._set_publication_state(
                    publication_id, EntityState.UNFINISHED, run_end
                )

        tx_outcomes = tuple(
            TransactionOutcome(
                tx_id=record.transaction.tx_id,
                state=record.state,
                arrival_time=record.transaction.arrival_time,
                batch_id=record.batch_id,
                completion_time=record.completion_time,
                rejection_reason=record.rejection_reason,
                batching_latency=record.batching_latency,
                queue_latency=record.queue_latency,
                service_latency=record.service_latency,
                retry_backoff_latency=record.retry_backoff_latency,
                confirmation_latency=record.confirmation_latency,
            )
            for record in self._tx.values()
        )
        publication_outcomes = tuple(
            PublicationOutcome(
                publication_id=publication_id,
                batch_id=record.batch.batch_id,
                state=record.state,
                prepared=record.prepared,
                attempts=tuple(record.attempts),
                confirmation_time=record.confirmation_time,
                retry_backoff_seconds=record.retry_backoff_seconds,
                rejection_reason=record.rejection_reason,
            )
            for publication_id, record in self._pub.items()
        )
        observation = run_end if run_end > 0 else horizon
        observed_external_busy = self._external_busy_seconds + sum(
            run_end - started_at for started_at in self._external_active_started.values()
        )
        return SimulationResult(
            strategy_id=self.strategy.strategy_id,
            measurement_horizon_seconds=horizon,
            termination_policy=self.simulation.termination_policy,
            run_end_time=run_end,
            workload_fingerprint=workload_fingerprint(transactions),
            batches=tuple(self._batches),
            transactions=tx_outcomes,
            publications=publication_outcomes,
            transitions=tuple(self._transitions),
            resource=ResourceAccounting(
                observation_end_time=observation,
                maximum_queue_depth=self._max_queue_depth,
                time_weighted_queue_depth=self._queue_area / observation,
                external_busy_server_seconds=observed_external_busy,
                external_service_concurrency=(
                    self.external_da.service_concurrency if self._is_external else None
                ),
                external_maximum_active_services=self._external_max_active,
                ethereum_slots_processed=self._eth_slots,
                ethereum_consumed_gas=self._eth_consumed,
                ethereum_available_gas_budget=(
                    self._eth_slots * self.ethereum.da_gas_budget_per_block
                ),
                ethereum_slot_gas=tuple(self._eth_slot_gas),
            ),
        )
