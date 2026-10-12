"""Ledger-derived metrics and validation for simulation results."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .config import EthereumConfig, ExternalDAConfig
from .domain import Transaction
from .engine import EntityState, SimulationResult


@dataclass(frozen=True, slots=True)
class MetricsSummary:
    offered_transactions: int
    completed_in_window: int
    completed_total: int
    failed_transactions: int
    rejected_transactions: int
    unfinished_transactions: int
    offered_rate_tps: float
    completed_throughput_tps: float
    drained_makespan_throughput_tps: float
    completion_ratio: float
    publication_attempts: int
    failed_attempts: int
    retries: int
    rejected_publications: int
    unfinished_publications: int
    total_attempted_cost_by_unit: dict[str, Decimal]
    cost_per_completed_transaction_by_unit: dict[str, Decimal | None]
    latency_percentiles_seconds: dict[str, float]
    mean_batching_latency_seconds: float
    mean_queue_latency_seconds: float
    mean_service_latency_seconds: float
    mean_retry_backoff_seconds: float
    mean_confirmation_latency_seconds: float
    raw_serialized_bytes: int
    logical_transaction_bytes: int
    encoded_logical_bytes: int
    attempted_encoded_bytes: int
    raw_framing_overhead_bytes: int
    encoded_overhead_bytes: int
    average_queue_depth: float
    maximum_queue_depth: int
    resource_utilization: float
    ethereum_consumed_gas: int
    ethereum_available_gas_budget: int


@dataclass(frozen=True, slots=True)
class ValidationReport:
    transaction_conservation: bool
    batch_conservation: bool
    capacity_invariant: bool
    temporal_ordering: bool
    latency_decomposition: bool

    @property
    def valid(self) -> bool:
        return all(
            (
                self.transaction_conservation,
                self.batch_conservation,
                self.capacity_invariant,
                self.temporal_ordering,
                self.latency_decomposition,
            )
        )


def _mean(values: Iterable[float]) -> float:
    collected = tuple(values)
    return sum(collected) / len(collected) if collected else 0.0


def _percentile(values: Iterable[float], percentile: float) -> float:
    """Linear interpolation using rank ``(n - 1) * percentile``."""

    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def summarize(result: SimulationResult) -> MetricsSummary:
    horizon = result.measurement_horizon_seconds
    state_counts = Counter(transaction.state for transaction in result.transactions)
    completed = [
        transaction
        for transaction in result.transactions
        if transaction.state == EntityState.COMPLETED
    ]
    completed_in_window = [
        transaction
        for transaction in completed
        if transaction.completion_time is not None and transaction.completion_time < horizon
    ]
    latencies = [
        transaction.end_to_end_latency
        for transaction in completed
        if transaction.end_to_end_latency is not None
    ]

    costs: dict[str, Decimal] = defaultdict(Decimal)
    expected_units = {
        publication.prepared.monetary_cost_unit for publication in result.publications
    }
    if not expected_units:
        expected_units = (
            {"MOCK_DA_UNIT"} if result.strategy_id == "mock_external_da" else {"wei"}
        )
    for unit in expected_units:
        costs[unit] = Decimal(0)
    attempts = []
    for publication in result.publications:
        for attempt in publication.attempts:
            attempts.append(attempt)
            costs[attempt.cost_unit] += attempt.cost
    cost_per_completed = {
        unit: (amount / len(completed) if completed else None)
        for unit, amount in costs.items()
    }

    logical_bytes = sum(
        transaction.size_bytes for batch in result.batches for transaction in batch.transactions
    )
    raw_bytes = sum(len(batch.raw_payload) for batch in result.batches)
    encoded_logical_bytes = sum(
        publication.prepared.encoded_bytes for publication in result.publications
    )
    attempted_encoded_bytes = sum(
        publication.prepared.encoded_bytes * len(publication.attempts)
        for publication in result.publications
    )
    observation = result.resource.observation_end_time
    if result.resource.ethereum_available_gas_budget:
        utilization = (
            result.resource.ethereum_consumed_gas
            / result.resource.ethereum_available_gas_budget
        )
    elif result.resource.external_service_concurrency and observation > 0:
        utilization = result.resource.external_busy_server_seconds / (
            result.resource.external_service_concurrency * observation
        )
    else:
        utilization = 0.0

    makespan_denominator = result.run_end_time
    return MetricsSummary(
        offered_transactions=len(result.transactions),
        completed_in_window=len(completed_in_window),
        completed_total=len(completed),
        failed_transactions=state_counts[EntityState.FAILED],
        rejected_transactions=state_counts[EntityState.REJECTED],
        unfinished_transactions=state_counts[EntityState.UNFINISHED],
        offered_rate_tps=len(result.transactions) / horizon,
        completed_throughput_tps=len(completed_in_window) / horizon,
        drained_makespan_throughput_tps=(
            len(completed) / makespan_denominator if makespan_denominator > 0 else 0.0
        ),
        completion_ratio=len(completed) / len(result.transactions) if result.transactions else 0.0,
        publication_attempts=len(attempts),
        failed_attempts=sum(attempt.succeeded is False for attempt in attempts),
        retries=sum(max(0, len(publication.attempts) - 1) for publication in result.publications),
        rejected_publications=sum(
            publication.state == EntityState.REJECTED for publication in result.publications
        ),
        unfinished_publications=sum(
            publication.state == EntityState.UNFINISHED for publication in result.publications
        ),
        total_attempted_cost_by_unit=dict(costs),
        cost_per_completed_transaction_by_unit=cost_per_completed,
        latency_percentiles_seconds={
            "p50": _percentile(latencies, 0.50),
            "p90": _percentile(latencies, 0.90),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        mean_batching_latency_seconds=_mean(
            transaction.batching_latency or 0.0 for transaction in completed
        ),
        mean_queue_latency_seconds=_mean(transaction.queue_latency for transaction in completed),
        mean_service_latency_seconds=_mean(
            transaction.service_latency for transaction in completed
        ),
        mean_retry_backoff_seconds=_mean(
            transaction.retry_backoff_latency for transaction in completed
        ),
        mean_confirmation_latency_seconds=_mean(
            transaction.confirmation_latency for transaction in completed
        ),
        raw_serialized_bytes=raw_bytes,
        logical_transaction_bytes=logical_bytes,
        encoded_logical_bytes=encoded_logical_bytes,
        attempted_encoded_bytes=attempted_encoded_bytes,
        raw_framing_overhead_bytes=raw_bytes - logical_bytes,
        encoded_overhead_bytes=encoded_logical_bytes - logical_bytes,
        average_queue_depth=result.resource.time_weighted_queue_depth,
        maximum_queue_depth=result.resource.maximum_queue_depth,
        resource_utilization=utilization,
        ethereum_consumed_gas=result.resource.ethereum_consumed_gas,
        ethereum_available_gas_budget=result.resource.ethereum_available_gas_budget,
    )


def validate_result(
    result: SimulationResult,
    input_transactions: tuple[Transaction, ...],
    *,
    ethereum: EthereumConfig,
    external_da: ExternalDAConfig,
) -> ValidationReport:
    input_ids = [transaction.tx_id for transaction in input_transactions]
    outcome_ids = [transaction.tx_id for transaction in result.transactions]
    terminal_states = {
        EntityState.COMPLETED,
        EntityState.REJECTED,
        EntityState.FAILED,
        EntityState.UNFINISHED,
    }
    transaction_conservation = (
        len(input_ids) == len(set(input_ids))
        and sorted(input_ids) == sorted(outcome_ids)
        and all(transaction.state in terminal_states for transaction in result.transactions)
    )

    batched_ids = [
        transaction.tx_id for batch in result.batches for transaction in batch.transactions
    ]
    rejected_before_batch = {
        transaction.tx_id
        for transaction in result.transactions
        if transaction.batch_id is None and transaction.state == EntityState.REJECTED
    }
    batch_conservation = (
        len(batched_ids) == len(set(batched_ids))
        and set(batched_ids).isdisjoint(rejected_before_batch)
        and set(batched_ids) | rejected_before_batch == set(input_ids)
    )

    capacity_invariant = (
        all(
            consumed <= ethereum.da_gas_budget_per_block
            for _, consumed in result.resource.ethereum_slot_gas
        )
        and result.resource.ethereum_consumed_gas
        == sum(consumed for _, consumed in result.resource.ethereum_slot_gas)
        and result.resource.external_maximum_active_services
        <= external_da.service_concurrency
        and result.resource.maximum_queue_depth
        <= (
            external_da.queue_capacity_requests
            if result.strategy_id == "mock_external_da"
            else ethereum.queue_capacity_requests
        )
    )

    temporal_ordering = True
    for publication in result.publications:
        previous_end = None
        for attempt in publication.attempts:
            if not (
                attempt.enqueue_time <= attempt.service_start_time
                and (
                    attempt.service_end_time is None
                    or attempt.service_start_time <= attempt.service_end_time
                )
            ):
                temporal_ordering = False
            if previous_end is not None and attempt.enqueue_time < previous_end:
                temporal_ordering = False
            if attempt.service_end_time is not None:
                previous_end = attempt.service_end_time

    latency_decomposition = True
    for transaction in result.transactions:
        if transaction.state == EntityState.COMPLETED:
            total = transaction.end_to_end_latency
            components = transaction.latency_component_sum
            if total is None or components is None or not math.isclose(
                total, components, rel_tol=1e-12, abs_tol=1e-12
            ):
                latency_decomposition = False

    return ValidationReport(
        transaction_conservation=transaction_conservation,
        batch_conservation=batch_conservation,
        capacity_invariant=capacity_invariant,
        temporal_ordering=temporal_ordering,
        latency_decomposition=latency_decomposition,
    )


def assert_cross_strategy_fairness(results: Iterable[SimulationResult]) -> None:
    collected = tuple(results)
    if not collected:
        raise ValueError("at least one result is required")
    workload_hash = collected[0].workload_fingerprint
    signature = tuple(
        (batch.batch_id, tuple(tx.tx_id for tx in batch.transactions), batch.raw_payload)
        for batch in collected[0].batches
    )
    for result in collected[1:]:
        candidate = tuple(
            (batch.batch_id, tuple(tx.tx_id for tx in batch.transactions), batch.raw_payload)
            for batch in result.batches
        )
        if result.workload_fingerprint != workload_hash or candidate != signature:
            raise ValueError("cross-strategy workload or batch membership mismatch")
