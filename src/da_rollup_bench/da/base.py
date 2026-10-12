"""Scheduling-neutral publication contracts consumed by the future event engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class PreparedPublication:
    """Requirements for one logical publication; this object performs no scheduling."""

    strategy_id: str
    publication_id: str
    raw_payload_bytes: int
    encoded_payload: bytes
    capacity_demand: int
    capacity_unit: str
    monetary_cost: Decimal
    monetary_cost_unit: str
    service_time_seconds: float | None
    admissible: bool = True
    rejection_reason: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.strategy_id or not self.publication_id:
            raise ValueError("strategy_id and publication_id must not be empty")
        if self.raw_payload_bytes < 0 or self.capacity_demand < 0:
            raise ValueError("byte and capacity values must be non-negative")
        if not self.capacity_unit or not self.monetary_cost_unit:
            raise ValueError("units must not be empty")
        if self.monetary_cost < 0:
            raise ValueError("monetary cost must be non-negative")
        if self.service_time_seconds is not None and self.service_time_seconds < 0:
            raise ValueError("service time must be non-negative")
        if self.admissible and self.rejection_reason is not None:
            raise ValueError("an admissible publication cannot have a rejection reason")
        if not self.admissible and not self.rejection_reason:
            raise ValueError("an inadmissible publication requires a rejection reason")

    @property
    def encoded_bytes(self) -> int:
        return len(self.encoded_payload)


class DAPublicationStrategy(Protocol):
    strategy_id: str

    def prepare(self, publication_id: str, raw_payload: bytes) -> PreparedPublication:
        """Return immutable resource/cost requirements without scheduling them."""
