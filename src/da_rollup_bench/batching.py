"""Deterministic transaction batching and canonical length-prefix serialization."""

from __future__ import annotations

from collections.abc import Iterable

from .config import BatchingConfig
from .domain import Batch, BatchingResult, RejectedTransaction, Transaction


class StatefulBatcher:
    """Timer-aware batching adapter for a deterministic event engine.

    The engine schedules ``deadline`` with ``generation``. A timeout carrying an
    older generation is stale and is ignored.
    """

    def __init__(self, config: BatchingConfig) -> None:
        self.config = config
        self._current: list[Transaction] = []
        self._current_bytes = 0
        self._generation = 0
        self._next_batch_index = 0

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def deadline(self) -> float | None:
        if not self._current:
            return None
        return self._current[0].arrival_time + self.config.max_wait_seconds

    @property
    def buffered_transactions(self) -> tuple[Transaction, ...]:
        return tuple(self._current)

    def _close(self, now: float, reason: str) -> Batch:
        if not self._current:
            raise RuntimeError("cannot close an empty batch")
        batch = Batch(
            batch_id=f"batch-{self._next_batch_index:08d}",
            transactions=tuple(self._current),
            opened_at=self._current[0].arrival_time,
            closed_at=now,
            close_reason=reason,
            raw_payload=serialize_transactions(self._current, self.config.length_prefix_bytes),
        )
        self._next_batch_index += 1
        self._current = []
        self._current_bytes = 0
        self._generation += 1
        return batch

    def on_transaction(
        self, transaction: Transaction, now: float
    ) -> tuple[tuple[Batch, ...], RejectedTransaction | None, tuple[int, float] | None]:
        """Accept one arrival and return closed batches, rejection, and a timer request."""

        if now != transaction.arrival_time:
            raise ValueError("transaction arrival time must equal event time")
        closed: list[Batch] = []
        prefix_maximum = (1 << (8 * self.config.length_prefix_bytes)) - 1
        record_bytes = self.config.length_prefix_bytes + transaction.size_bytes
        if transaction.size_bytes > prefix_maximum:
            return (), RejectedTransaction(transaction, "length_prefix_overflow"), None
        if record_bytes > self.config.max_raw_bytes:
            return (), RejectedTransaction(transaction, "individually_oversized"), None

        if self._current and self._current_bytes + record_bytes > self.config.max_raw_bytes:
            closed.append(self._close(now, "max_bytes"))

        was_empty = not self._current
        self._current.append(transaction)
        self._current_bytes += record_bytes
        timer_request = None
        if was_empty:
            self._generation += 1
            timer_request = (self._generation, now + self.config.max_wait_seconds)

        if len(self._current) == self.config.max_transactions:
            closed.append(self._close(now, "max_transactions"))
            timer_request = None
        elif self._current_bytes == self.config.max_raw_bytes:
            closed.append(self._close(now, "max_bytes"))
            timer_request = None
        return tuple(closed), None, timer_request

    def on_timeout(self, generation: int, now: float) -> Batch | None:
        if generation != self._generation or not self._current:
            return None
        deadline = self.deadline
        if deadline is None or now < deadline:
            raise ValueError("timeout occurred before the active deadline")
        return self._close(deadline, "max_wait")

    def flush(self, now: float) -> Batch | None:
        if not self._current:
            return None
        if now < self._current[-1].arrival_time:
            raise ValueError("flush cannot precede a buffered arrival")
        return self._close(now, "end_of_window")


def serialize_transactions(
    transactions: Iterable[Transaction], length_prefix_bytes: int = 4
) -> bytes:
    """Serialize payloads as big-endian length followed by exact payload bytes."""

    if length_prefix_bytes not in (1, 2, 4, 8):
        raise ValueError("length_prefix_bytes must be one of 1, 2, 4, or 8")
    maximum_length = (1 << (8 * length_prefix_bytes)) - 1
    output = bytearray()
    for transaction in transactions:
        if transaction.size_bytes > maximum_length:
            raise ValueError("transaction payload does not fit length prefix")
        output.extend(transaction.size_bytes.to_bytes(length_prefix_bytes, "big"))
        output.extend(transaction.payload)
    return bytes(output)


def deserialize_payloads(data: bytes, length_prefix_bytes: int = 4) -> tuple[bytes, ...]:
    """Parse canonical serialization and reject truncated or malformed input."""

    if length_prefix_bytes not in (1, 2, 4, 8):
        raise ValueError("length_prefix_bytes must be one of 1, 2, 4, or 8")
    offset = 0
    payloads = []
    while offset < len(data):
        prefix_end = offset + length_prefix_bytes
        if prefix_end > len(data):
            raise ValueError("truncated transaction length prefix")
        length = int.from_bytes(data[offset:prefix_end], "big")
        payload_end = prefix_end + length
        if payload_end > len(data):
            raise ValueError("truncated transaction payload")
        payloads.append(data[prefix_end:payload_end])
        offset = payload_end
    return tuple(payloads)


def batch_transactions(
    transactions: Iterable[Transaction],
    config: BatchingConfig,
    *,
    flush_time: float | None = None,
) -> BatchingResult:
    """Batch ordered arrivals using count, framed-byte, and oldest-wait limits."""

    ordered = tuple(transactions)
    if any(right.arrival_time < left.arrival_time for left, right in zip(ordered, ordered[1:])):
        raise ValueError("transactions must be ordered by non-decreasing arrival time")
    if flush_time is not None and ordered and flush_time < ordered[-1].arrival_time:
        raise ValueError("flush_time cannot precede the last arrival")

    batches: list[Batch] = []
    rejected: list[RejectedTransaction] = []
    current: list[Transaction] = []
    current_bytes = 0

    def close(closed_at: float, reason: str) -> None:
        nonlocal current, current_bytes
        if not current:
            return
        batches.append(
            Batch(
                batch_id=f"batch-{len(batches):08d}",
                transactions=tuple(current),
                opened_at=current[0].arrival_time,
                closed_at=closed_at,
                close_reason=reason,
                raw_payload=serialize_transactions(current, config.length_prefix_bytes),
            )
        )
        current = []
        current_bytes = 0

    for transaction in ordered:
        record_bytes = config.length_prefix_bytes + transaction.size_bytes
        maximum_payload_length = (1 << (8 * config.length_prefix_bytes)) - 1
        if transaction.size_bytes > maximum_payload_length:
            if current and transaction.arrival_time >= current[0].arrival_time + config.max_wait_seconds:
                close(current[0].arrival_time + config.max_wait_seconds, "max_wait")
            rejected.append(RejectedTransaction(transaction, "length_prefix_overflow"))
            continue
        if record_bytes > config.max_raw_bytes:
            if current and transaction.arrival_time >= current[0].arrival_time + config.max_wait_seconds:
                close(current[0].arrival_time + config.max_wait_seconds, "max_wait")
            rejected.append(RejectedTransaction(transaction, "individually_oversized"))
            continue

        if current and transaction.arrival_time >= current[0].arrival_time + config.max_wait_seconds:
            close(current[0].arrival_time + config.max_wait_seconds, "max_wait")

        if current and current_bytes + record_bytes > config.max_raw_bytes:
            close(transaction.arrival_time, "max_bytes")

        current.append(transaction)
        current_bytes += record_bytes

        if len(current) == config.max_transactions:
            close(transaction.arrival_time, "max_transactions")
        elif current_bytes == config.max_raw_bytes:
            close(transaction.arrival_time, "max_bytes")

    if current:
        deadline = current[0].arrival_time + config.max_wait_seconds
        effective_flush = ordered[-1].arrival_time if flush_time is None else flush_time
        if effective_flush >= deadline:
            close(deadline, "max_wait")
        else:
            close(effective_flush, "end_of_workload")

    return BatchingResult(tuple(batches), tuple(rejected))
