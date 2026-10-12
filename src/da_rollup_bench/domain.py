"""Immutable domain records shared by workload and batching components."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Transaction:
    tx_id: str
    arrival_time: float
    payload: bytes

    def __post_init__(self) -> None:
        if not self.tx_id:
            raise ValueError("tx_id must not be empty")
        if self.arrival_time < 0:
            raise ValueError("arrival_time must be non-negative")
        if not self.payload:
            raise ValueError("payload must not be empty")

    @property
    def size_bytes(self) -> int:
        return len(self.payload)


@dataclass(frozen=True, slots=True)
class Batch:
    batch_id: str
    transactions: tuple[Transaction, ...]
    opened_at: float
    closed_at: float
    close_reason: str
    raw_payload: bytes

    def __post_init__(self) -> None:
        if not self.transactions:
            raise ValueError("a batch must contain at least one transaction")
        if self.closed_at < self.opened_at:
            raise ValueError("batch cannot close before it opens")


@dataclass(frozen=True, slots=True)
class RejectedTransaction:
    transaction: Transaction
    reason: str


@dataclass(frozen=True, slots=True)
class BatchingResult:
    batches: tuple[Batch, ...]
    rejected: tuple[RejectedTransaction, ...]

