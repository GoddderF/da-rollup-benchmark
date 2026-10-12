from decimal import Decimal

import pytest

from da_rollup_bench.config import ExternalDAConfig, TrustAssumptions
from da_rollup_bench.da.external_mock import MockExternalDAStrategy


def config(**overrides: object) -> ExternalDAConfig:
    values = {
        "fixed_fee": "1.25",
        "per_byte_fee": "0.01",
        "bandwidth_bytes_per_second": 100,
        "fixed_service_time_seconds": 0.5,
        "max_payload_bytes": 10,
        "queue_capacity_requests": 3,
        "service_concurrency": 2,
        "availability_probability": 0.5,
        "availability_seed": 42,
        "max_retries": 2,
        "initial_backoff_seconds": 0.25,
        "backoff_multiplier": 3,
        "trust_assumptions": TrustAssumptions(
            operator_model="generic operators",
            data_availability_guarantee="independent seeded attempts",
            settlement_relationship="not modeled",
            notes="mock only",
        ),
    }
    values.update(overrides)
    return ExternalDAConfig.model_validate(values)


def test_fee_service_demand_capacity_and_units_are_exact() -> None:
    result = MockExternalDAStrategy(config()).prepare_detailed("batch-7", b"abcdef")
    publication = result.publication
    assert publication.monetary_cost == Decimal("1.31")
    assert publication.monetary_cost_unit == "MOCK_DA_UNIT"
    assert publication.service_time_seconds == pytest.approx(0.56)
    assert publication.capacity_demand == 6
    assert publication.capacity_unit == "bytes"
    assert result.admissible is True
    assert result.queue_capacity_requests == 3
    assert result.service_concurrency == 2


def test_empty_payload_pays_only_fixed_fee() -> None:
    result = MockExternalDAStrategy(config()).prepare("empty", b"")
    assert result.monetary_cost == Decimal("1.25")
    assert result.service_time_seconds == pytest.approx(0.5)


def test_oversized_payload_is_marked_inadmissible_without_scheduling() -> None:
    strategy = MockExternalDAStrategy(config())
    result = strategy.prepare_detailed("large", b"x" * 11)
    assert result.admissible is False
    assert result.publication.encoded_bytes == 11
    assert strategy.prepare("large", b"x" * 11).admissible is False
    assert (
        result.publication.rejection_reason == "payload_exceeds_external_da_capacity"
    )


def test_seeded_availability_is_order_independent_and_repeatable() -> None:
    strategy = MockExternalDAStrategy(config())
    forward = {
        (publication, attempt): strategy.attempt_succeeds(publication, attempt)
        for publication in ("a", "b", "c")
        for attempt in (1, 2, 3)
    }
    reverse = {
        (publication, attempt): strategy.attempt_succeeds(publication, attempt)
        for publication in reversed(("a", "b", "c"))
        for attempt in reversed((1, 2, 3))
    }
    assert forward == reverse
    assert set(forward.values()) == {False, True}


@pytest.mark.parametrize(("probability", "expected"), [(0, False), (1, True)])
def test_availability_probability_extremes(probability: float, expected: bool) -> None:
    strategy = MockExternalDAStrategy(config(availability_probability=probability))
    assert strategy.attempt_succeeds("batch", 1) is expected


def test_bounded_attempts_and_exponential_backoff() -> None:
    strategy = MockExternalDAStrategy(config())
    assert strategy.retry_backoff_seconds(1) == pytest.approx(0.25)
    assert strategy.retry_backoff_seconds(2) == pytest.approx(0.75)
    with pytest.raises(ValueError):
        strategy.retry_backoff_seconds(3)
    with pytest.raises(ValueError):
        strategy.attempt_succeeds("batch", 4)


def test_trust_assumptions_are_exposed_not_scored() -> None:
    result = MockExternalDAStrategy(config()).prepare_detailed("batch", b"x")
    assert result.trust_assumptions.operator_model == "generic operators"
    assert not hasattr(result.trust_assumptions, "security_score")
