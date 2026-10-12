"""Generic mock external DA publication requirements and deterministic outcomes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from ..config import ExternalDAConfig, TrustAssumptions
from .base import PreparedPublication


@dataclass(frozen=True, slots=True)
class MockExternalDAResult:
    publication: PreparedPublication
    admissible: bool
    max_payload_bytes: int
    queue_capacity_requests: int
    service_concurrency: int
    max_retries: int
    trust_assumptions: TrustAssumptions


class MockExternalDAStrategy:
    """Prepare requests and deterministic retry outcomes; owns no event queue."""

    strategy_id = "mock_external_da"

    def __init__(self, config: ExternalDAConfig) -> None:
        self.config = config

    def prepare_detailed(self, publication_id: str, raw_payload: bytes) -> MockExternalDAResult:
        payload_bytes = len(raw_payload)
        fee = self.config.fixed_fee + self.config.per_byte_fee * payload_bytes
        service_time = (
            self.config.fixed_service_time_seconds
            + payload_bytes / self.config.bandwidth_bytes_per_second
        )
        admissible = payload_bytes <= self.config.max_payload_bytes
        publication = PreparedPublication(
            strategy_id=self.strategy_id,
            publication_id=publication_id,
            raw_payload_bytes=payload_bytes,
            encoded_payload=raw_payload,
            capacity_demand=payload_bytes,
            capacity_unit="bytes",
            monetary_cost=fee,
            monetary_cost_unit=self.config.mock_currency_unit,
            service_time_seconds=service_time,
            admissible=admissible,
            rejection_reason=None if admissible else "payload_exceeds_external_da_capacity",
            metadata={
                "profile_name": self.config.profile_name.value,
                "queue_capacity_requests": self.config.queue_capacity_requests,
                "service_concurrency": self.config.service_concurrency,
                "max_retries": self.config.max_retries,
            },
        )
        return MockExternalDAResult(
            publication=publication,
            admissible=admissible,
            max_payload_bytes=self.config.max_payload_bytes,
            queue_capacity_requests=self.config.queue_capacity_requests,
            service_concurrency=self.config.service_concurrency,
            max_retries=self.config.max_retries,
            trust_assumptions=self.config.trust_assumptions,
        )

    def prepare(self, publication_id: str, raw_payload: bytes) -> PreparedPublication:
        return self.prepare_detailed(publication_id, raw_payload).publication

    def attempt_succeeds(self, publication_id: str, attempt_number: int) -> bool:
        """Return an order-independent seeded Bernoulli result for a 1-based attempt."""

        if not publication_id:
            raise ValueError("publication_id must not be empty")
        total_attempts = 1 + self.config.max_retries
        if attempt_number < 1 or attempt_number > total_attempts:
            raise ValueError(f"attempt_number must be in [1, {total_attempts}]")
        probability = self.config.availability_probability
        if probability == 0:
            return False
        if probability == 1:
            return True
        material = (
            f"sc6019:external-da:{self.config.availability_seed}:"
            f"{publication_id}:{attempt_number}"
        ).encode("utf-8")
        sample = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") / 2**64
        return sample < probability

    def retry_backoff_seconds(self, failed_attempt_number: int) -> float:
        """Delay after a failed attempt; the engine decides whether to enqueue the retry."""

        if failed_attempt_number < 1 or failed_attempt_number > self.config.max_retries:
            raise ValueError(
                f"failed_attempt_number must be in [1, {self.config.max_retries}]"
            )
        return self.config.initial_backoff_seconds * (
            self.config.backoff_multiplier ** (failed_attempt_number - 1)
        )
