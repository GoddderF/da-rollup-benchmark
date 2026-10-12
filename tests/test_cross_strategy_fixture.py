import json
from pathlib import Path

from da_rollup_bench.config import (
    BatchingConfig,
    CompressionConfig,
    EthereumConfig,
    ExternalDAConfig,
    SimulationConfig,
)
from da_rollup_bench.da.compressed_calldata import CompressedCalldataStrategy
from da_rollup_bench.da.external_mock import MockExternalDAStrategy
from da_rollup_bench.da.raw_calldata import RawCalldataStrategy
from da_rollup_bench.domain import Transaction
from da_rollup_bench.engine import SimulationEngine
from da_rollup_bench.metrics import assert_cross_strategy_fairness, summarize, validate_result


def test_reproducible_cross_strategy_validation_fixture() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "cross_strategy_small.json").read_text(
            encoding="utf-8"
        )
    )
    transactions = tuple(
        Transaction(item["tx_id"], item["arrival_time"], bytes.fromhex(item["payload_hex"]))
        for item in fixture["transactions"]
    )
    batching = BatchingConfig.model_validate(fixture["batching"])
    ethereum = EthereumConfig(
        block_interval_seconds=1,
        da_gas_budget_per_block=1_000_000,
        effective_gas_price_wei=2,
    )
    external = ExternalDAConfig(
        availability_probability=1,
        bandwidth_bytes_per_second=1_000,
        fixed_service_time_seconds=0.1,
    )
    simulation = SimulationConfig(measurement_horizon_seconds=5)
    strategies = (
        RawCalldataStrategy(ethereum),
        CompressedCalldataStrategy(CompressionConfig(level=6), ethereum),
        MockExternalDAStrategy(external),
    )
    results = tuple(
        SimulationEngine(
            batching=batching,
            strategy=strategy,
            ethereum=ethereum,
            external_da=external,
            simulation=simulation,
        ).run(transactions)
        for strategy in strategies
    )

    assert_cross_strategy_fairness(results)
    expected_ids = [item["tx_id"] for item in fixture["transactions"]]
    expected_arrivals = [item["arrival_time"] for item in fixture["transactions"]]
    expected_payloads = [bytes.fromhex(item["payload_hex"]) for item in fixture["transactions"]]
    for result in results:
        assert [item.tx_id for item in result.transactions] == expected_ids
        assert [item.arrival_time for item in result.transactions] == expected_arrivals
        assert [tx.payload for batch in result.batches for tx in batch.transactions] == expected_payloads
        assert [
            [tx.tx_id for tx in batch.transactions] for batch in result.batches
        ] == fixture["expected_batch_membership"]
        assert validate_result(
            result, transactions, ethereum=ethereum, external_da=external
        ).valid

    raw, compressed, mock = results
    assert raw.publications[0].prepared.encoded_payload == raw.batches[0].raw_payload
    assert compressed.publications[0].prepared.encoded_bytes != raw.publications[0].prepared.encoded_bytes
    assert mock.publications[0].prepared.capacity_unit == "bytes"
    assert {attempt.cost_unit for pub in raw.publications for attempt in pub.attempts} == {"wei"}
    assert {attempt.cost_unit for pub in mock.publications for attempt in pub.attempts} == {
        "MOCK_DA_UNIT"
    }
    assert set(summarize(raw).total_attempted_cost_by_unit) == {"wei"}
    assert set(summarize(mock).total_attempted_cost_by_unit) == {"MOCK_DA_UNIT"}
