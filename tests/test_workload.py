import pytest

from da_rollup_bench.config import (
    ArrivalProcess,
    ContentModel,
    SizeDistribution,
    WorkloadConfig,
)
from da_rollup_bench.workload import generate_workload, workload_fingerprint


def test_fixed_workload_has_exact_arrivals_and_payload_fixture() -> None:
    config = WorkloadConfig(
        arrival_process=ArrivalProcess.FIXED,
        arrival_rate_tps=2,
        duration_seconds=2,
        seed=17,
        fixed_size_bytes=5,
        content_model=ContentModel.REPEATED,
        repeated_pattern_hex="aabb",
    )
    workload = generate_workload(config)
    assert [tx.arrival_time for tx in workload] == [0.0, 0.5, 1.0, 1.5]
    assert [tx.tx_id for tx in workload] == [f"tx-{i:08d}" for i in range(4)]
    assert all(tx.payload == bytes.fromhex("aabbaabb aa".replace(" ", "")) for tx in workload)


def test_same_seed_and_config_are_byte_deterministic() -> None:
    config = WorkloadConfig(duration_seconds=3, arrival_rate_tps=4, seed=99)
    first = generate_workload(config)
    second = generate_workload(config)
    assert first == second
    assert workload_fingerprint(first) == workload_fingerprint(second)


def test_different_seed_changes_fingerprint() -> None:
    first = generate_workload(WorkloadConfig(duration_seconds=3, seed=1))
    second = generate_workload(WorkloadConfig(duration_seconds=3, seed=2))
    assert workload_fingerprint(first) != workload_fingerprint(second)


def test_arrival_stream_is_independent_of_payload_content_model() -> None:
    common = dict(duration_seconds=3, arrival_rate_tps=4, seed=99, fixed_size_bytes=16)
    entropy = generate_workload(
        WorkloadConfig(**common, content_model=ContentModel.HIGH_ENTROPY)
    )
    repeated = generate_workload(
        WorkloadConfig(**common, content_model=ContentModel.REPEATED)
    )
    assert [item.arrival_time for item in entropy] == [item.arrival_time for item in repeated]
    assert [item.payload for item in entropy] != [item.payload for item in repeated]


def test_poisson_arrivals_are_ordered_bounded_and_capped() -> None:
    config = WorkloadConfig(
        arrival_process=ArrivalProcess.POISSON,
        arrival_rate_tps=100,
        duration_seconds=10,
        max_transactions=7,
        seed=3,
    )
    workload = generate_workload(config)
    times = [tx.arrival_time for tx in workload]
    assert len(workload) == 7
    assert times == sorted(times)
    assert all(0 <= timestamp < 10 for timestamp in times)


def test_zero_fraction_extremes_are_exact() -> None:
    all_zero = generate_workload(
        WorkloadConfig(
            arrival_process=ArrivalProcess.FIXED,
            arrival_rate_tps=1,
            duration_seconds=1,
            fixed_size_bytes=16,
            content_model=ContentModel.ZERO_FRACTION,
            zero_probability=1,
        )
    )[0]
    no_zero = generate_workload(
        WorkloadConfig(
            arrival_process=ArrivalProcess.FIXED,
            arrival_rate_tps=1,
            duration_seconds=1,
            fixed_size_bytes=64,
            content_model=ContentModel.ZERO_FRACTION,
            zero_probability=0,
        )
    )[0]
    assert all_zero.payload == bytes(16)
    assert 0 not in no_zero.payload


def test_categorical_sizes_come_from_configured_support() -> None:
    workload = generate_workload(
        WorkloadConfig(
            arrival_process=ArrivalProcess.FIXED,
            arrival_rate_tps=10,
            duration_seconds=1,
            size_distribution=SizeDistribution.CATEGORICAL,
            categorical_sizes_bytes=(8, 13),
            categorical_weights=(1, 2),
        )
    )
    assert {tx.size_bytes for tx in workload} <= {8, 13}


def test_workload_transaction_limit_must_be_positive() -> None:
    with pytest.raises(Exception):
        WorkloadConfig(max_transactions=0)
