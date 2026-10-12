from decimal import Decimal

import pytest

from da_rollup_bench.batching import StatefulBatcher, batch_transactions
from da_rollup_bench.config import (
    BatchingConfig,
    CompressionConfig,
    EthereumConfig,
    ExternalDAConfig,
    SimulationConfig,
    TerminationPolicy,
)
from da_rollup_bench.da.compressed_calldata import CompressedCalldataStrategy
from da_rollup_bench.da.external_mock import MockExternalDAStrategy
from da_rollup_bench.da.raw_calldata import RawCalldataStrategy
from da_rollup_bench.domain import Transaction
from da_rollup_bench.engine import EntityState, SimulationEngine
from da_rollup_bench.metrics import (
    assert_cross_strategy_fairness,
    summarize,
    validate_result,
)


def tx(index: int, arrival: float, payload: bytes = b"a") -> Transaction:
    return Transaction(f"tx-{index}", arrival, payload)


def ethereum_config(**overrides: object) -> EthereumConfig:
    values = {
        "effective_gas_price_wei": 2,
        "block_interval_seconds": 10,
        "da_gas_budget_per_block": 100_000,
        "queue_capacity_requests": 100,
    }
    values.update(overrides)
    return EthereumConfig.model_validate(values)


def external_config(**overrides: object) -> ExternalDAConfig:
    values = {
        "fixed_fee": "2",
        "per_byte_fee": "0.1",
        "bandwidth_bytes_per_second": 5,
        "fixed_service_time_seconds": 1,
        "max_payload_bytes": 10_000,
        "queue_capacity_requests": 100,
        "service_concurrency": 1,
        "availability_probability": 1,
        "availability_seed": 5,
        "max_retries": 2,
        "initial_backoff_seconds": 3,
        "backoff_multiplier": 2,
    }
    values.update(overrides)
    return ExternalDAConfig.model_validate(values)


def simulation(
    horizon: float = 20,
    policy: TerminationPolicy = TerminationPolicy.DRAIN,
    **overrides: object,
) -> SimulationConfig:
    values = {
        "measurement_horizon_seconds": horizon,
        "termination_policy": policy,
        "ethereum_confirmation_delay_seconds": 0,
        "external_confirmation_delay_seconds": 0,
    }
    values.update(overrides)
    return SimulationConfig.model_validate(values)


def run_external(
    transactions: tuple[Transaction, ...],
    *,
    batching: BatchingConfig | None = None,
    external: ExternalDAConfig | None = None,
    sim: SimulationConfig | None = None,
):
    ext = external or external_config()
    return SimulationEngine(
        batching=batching or BatchingConfig(max_transactions=1),
        strategy=MockExternalDAStrategy(ext),
        ethereum=ethereum_config(),
        external_da=ext,
        simulation=sim or simulation(),
    ).run(transactions)


def run_ethereum(
    transactions: tuple[Transaction, ...],
    *,
    ethereum: EthereumConfig | None = None,
    sim: SimulationConfig | None = None,
):
    eth = ethereum or ethereum_config()
    return SimulationEngine(
        batching=BatchingConfig(max_transactions=1),
        strategy=RawCalldataStrategy(eth),
        ethereum=eth,
        external_da=external_config(),
        simulation=sim or simulation(horizon=40),
    ).run(transactions)


def test_stateful_batcher_matches_offline_reference_and_ignores_stale_timer() -> None:
    transactions = (tx(0, 0), tx(1, 0.5), tx(2, 3))
    config = BatchingConfig(max_transactions=2, max_raw_bytes=100, max_wait_seconds=2)
    reference = batch_transactions(transactions, config, flush_time=4)
    adapter = StatefulBatcher(config)
    batches = []
    timers = []
    for transaction in transactions:
        while timers and timers[0][1] <= transaction.arrival_time:
            generation, deadline = timers.pop(0)
            batch = adapter.on_timeout(generation, deadline)
            if batch:
                batches.append(batch)
        closed, rejection, timer = adapter.on_transaction(transaction, transaction.arrival_time)
        assert rejection is None
        batches.extend(closed)
        if timer:
            timers.append(timer)
    stale_generation = 1
    assert adapter.on_timeout(stale_generation, 4) is None
    final = adapter.flush(4)
    if final:
        batches.append(final)
    assert [batch.raw_payload for batch in batches] == [
        batch.raw_payload for batch in reference.batches
    ]
    assert [batch.closed_at for batch in batches] == [
        batch.closed_at for batch in reference.batches
    ]


def test_one_transaction_one_batch_success_hand_calculated_latency() -> None:
    result = run_external(
        (tx(0, 0),),
        sim=simulation(horizon=20, external_confirmation_delay_seconds=3),
    )
    outcome = result.transactions[0]
    # Framed payload is 5 bytes: service = 1 + 5/5 = 2; confirmation = 3.
    assert outcome.state == EntityState.COMPLETED
    assert outcome.batching_latency == 0
    assert outcome.queue_latency == 0
    assert outcome.service_latency == 2
    assert outcome.retry_backoff_latency == 0
    assert outcome.confirmation_latency == 3
    assert outcome.end_to_end_latency == 5
    assert outcome.latency_component_sum == 5


def test_multiple_publications_share_slot_then_head_carries_to_next_slot() -> None:
    probe = RawCalldataStrategy(ethereum_config()).prepare("probe", b"\x00\x00\x00\x01a")
    budget = probe.capacity_demand * 2
    result = run_ethereum(
        (tx(0, 0), tx(1, 0), tx(2, 0)),
        ethereum=ethereum_config(da_gas_budget_per_block=budget),
    )
    completion_times = [item.completion_time for item in result.transactions]
    assert completion_times == [10, 10, 20]
    assert result.resource.ethereum_slot_gas == (
        (10, probe.capacity_demand * 2),
        (20, probe.capacity_demand),
    )


def test_publication_exceeding_full_gas_budget_is_rejected_without_cost() -> None:
    result = run_ethereum(
        (tx(0, 0),), ethereum=ethereum_config(da_gas_budget_per_block=21_000)
    )
    assert result.transactions[0].state == EntityState.REJECTED
    assert result.transactions[0].rejection_reason == "exceeds_block_gas_budget"
    assert not result.publications[0].attempts


def test_external_service_uses_multiple_concurrent_slots() -> None:
    result = run_external(
        (tx(0, 0), tx(1, 0), tx(2, 0)),
        external=external_config(service_concurrency=2),
    )
    assert [item.completion_time for item in result.transactions] == [2, 2, 4]
    assert result.resource.external_maximum_active_services == 2
    assert result.resource.maximum_queue_depth == 1


def test_failed_attempt_then_success_has_non_overlapping_hand_calculated_latency() -> None:
    ext = external_config(availability_probability=0.5, availability_seed=5)
    result = run_external(
        (tx(0, 0),),
        external=ext,
        sim=simulation(horizon=20, external_confirmation_delay_seconds=4),
    )
    outcome = result.transactions[0]
    publication = result.publications[0]
    assert [attempt.succeeded for attempt in publication.attempts] == [False, True]
    # Two 2-second services + 3-second backoff + 4-second confirmation.
    assert outcome.batching_latency == 0
    assert outcome.queue_latency == 0
    assert outcome.service_latency == 4
    assert outcome.retry_backoff_latency == 3
    assert outcome.confirmation_latency == 4
    assert outcome.end_to_end_latency == 11
    assert outcome.latency_component_sum == 11


def test_exhausted_attempts_fail_and_charge_every_attempt() -> None:
    ext = external_config(availability_probability=0, max_retries=2)
    result = run_external((tx(0, 0),), external=ext)
    summary = summarize(result)
    assert result.transactions[0].state == EntityState.FAILED
    assert summary.publication_attempts == 3
    assert summary.failed_attempts == 3
    # Each attempt costs 2 + 0.1*5 = 2.5 mock units.
    assert summary.total_attempted_cost_by_unit == {"MOCK_DA_UNIT": Decimal("7.5")}


def test_external_queue_saturation_rejects_third_publication() -> None:
    ext = external_config(service_concurrency=1, queue_capacity_requests=1)
    result = run_external((tx(0, 0), tx(1, 0), tx(2, 0)), external=ext)
    assert [item.state for item in result.transactions].count(EntityState.REJECTED) == 1
    assert any(item.rejection_reason == "external_queue_full" for item in result.transactions)


def test_batch_timeout_precedes_simultaneous_arrival() -> None:
    result = run_external(
        (tx(0, 0), tx(1, 2)),
        batching=BatchingConfig(max_transactions=10, max_raw_bytes=100, max_wait_seconds=2),
        sim=simulation(horizon=10),
    )
    assert [[item.tx_id for item in batch.transactions] for batch in result.batches] == [
        ["tx-0"],
        ["tx-1"],
    ]
    assert result.batches[0].closed_at == 2
    assert result.batches[0].close_reason == "max_wait"


def test_drain_and_truncate_use_window_completions_for_primary_throughput() -> None:
    ext = external_config(fixed_service_time_seconds=4, bandwidth_bytes_per_second=5)
    truncate = run_external(
        (tx(0, 0),),
        external=ext,
        sim=simulation(horizon=2, policy=TerminationPolicy.TRUNCATE),
    )
    drain = run_external(
        (tx(0, 0),),
        external=ext,
        sim=simulation(horizon=2, policy=TerminationPolicy.DRAIN),
    )
    truncate_metrics = summarize(truncate)
    drain_metrics = summarize(drain)
    assert truncate.transactions[0].state == EntityState.UNFINISHED
    assert drain.transactions[0].state == EntityState.COMPLETED
    assert truncate_metrics.completed_throughput_tps == 0
    assert drain_metrics.completed_throughput_tps == 0
    assert drain_metrics.drained_makespan_throughput_tps == pytest.approx(1 / 5)
    assert truncate_metrics.total_attempted_cost_by_unit == {
        "MOCK_DA_UNIT": Decimal("2.5")
    }


@pytest.mark.parametrize(
    ("arrivals", "expected_completed", "minimum_unfinished"),
    [((0.0,), 1, 0), ((0.0, 1.0), 2, 0), ((0.0, 0.1, 0.2, 0.3), 2, 2)],
    ids=["underload", "near-capacity", "overload"],
)
def test_load_regimes_are_deterministic(
    arrivals: tuple[float, ...], expected_completed: int, minimum_unfinished: int
) -> None:
    ext = external_config(
        fixed_service_time_seconds=0,
        bandwidth_bytes_per_second=5,
        queue_capacity_requests=10,
    )
    result = run_external(
        tuple(tx(i, arrival) for i, arrival in enumerate(arrivals)),
        external=ext,
        sim=simulation(horizon=2.5, policy=TerminationPolicy.TRUNCATE),
    )
    summary = summarize(result)
    assert summary.completed_total == expected_completed
    assert summary.unfinished_transactions >= minimum_unfinished


def test_identical_workload_and_batches_across_all_three_strategies() -> None:
    transactions = (tx(0, 0, b"abc"), tx(1, 0.2, b"def"), tx(2, 3, b"ghi"))
    batching = BatchingConfig(max_transactions=2, max_raw_bytes=100, max_wait_seconds=2)
    eth = ethereum_config(block_interval_seconds=1, da_gas_budget_per_block=1_000_000)
    ext = external_config(bandwidth_bytes_per_second=1_000_000)
    sim = simulation(horizon=10)
    strategies = (
        RawCalldataStrategy(eth),
        CompressedCalldataStrategy(CompressionConfig(), eth),
        MockExternalDAStrategy(ext),
    )
    results = tuple(
        SimulationEngine(
            batching=batching,
            strategy=strategy,
            ethereum=eth,
            external_da=ext,
            simulation=sim,
        ).run(transactions)
        for strategy in strategies
    )
    assert_cross_strategy_fairness(results)
    assert len({result.workload_fingerprint for result in results}) == 1


def test_validation_reports_conservation_capacity_and_temporal_invariants() -> None:
    transactions = (tx(0, 0), tx(1, 0.5), tx(2, 1))
    ext = external_config(service_concurrency=2)
    result = run_external(transactions, external=ext)
    report = validate_result(
        result, transactions, ethereum=ethereum_config(), external_da=ext
    )
    assert report.valid


def test_replay_is_identical_for_same_inputs_and_runtime() -> None:
    transactions = (tx(0, 0), tx(1, 0.25), tx(2, 0.5))
    first = run_external(transactions)
    second = run_external(transactions)
    assert first == second
