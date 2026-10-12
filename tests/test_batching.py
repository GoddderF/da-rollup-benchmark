import pytest

from da_rollup_bench.batching import (
    batch_transactions,
    deserialize_payloads,
    serialize_transactions,
)
from da_rollup_bench.config import BatchingConfig
from da_rollup_bench.domain import Transaction


def tx(index: int, time: float, payload: bytes) -> Transaction:
    return Transaction(f"tx-{index}", time, payload)


def test_serialization_golden_fixture_and_round_trip() -> None:
    transactions = (tx(0, 0, b"ab"), tx(1, 0, b"\x00"))
    encoded = serialize_transactions(transactions, length_prefix_bytes=2)
    assert encoded == b"\x00\x02ab\x00\x01\x00"
    assert deserialize_payloads(encoded, 2) == (b"ab", b"\x00")


@pytest.mark.parametrize("malformed", [b"\x00", b"\x00\x03ab"])
def test_deserializer_rejects_truncation(malformed: bytes) -> None:
    with pytest.raises(ValueError, match="truncated"):
        deserialize_payloads(malformed, 2)


def test_count_limit_closes_batch_at_triggering_arrival() -> None:
    result = batch_transactions(
        (tx(0, 0.0, b"a"), tx(1, 0.2, b"b"), tx(2, 0.4, b"c")),
        BatchingConfig(max_transactions=2, max_raw_bytes=100, max_wait_seconds=10),
        flush_time=1,
    )
    assert [len(batch.transactions) for batch in result.batches] == [2, 1]
    assert result.batches[0].close_reason == "max_transactions"
    assert result.batches[0].closed_at == 0.2


def test_overflowing_transaction_moves_to_next_batch() -> None:
    config = BatchingConfig(
        max_transactions=10,
        max_raw_bytes=12,
        max_wait_seconds=10,
        length_prefix_bytes=2,
    )
    result = batch_transactions(
        (tx(0, 0.0, b"12345"), tx(1, 0.1, b"67890")), config, flush_time=1
    )
    assert [[item.tx_id for item in batch.transactions] for batch in result.batches] == [
        ["tx-0"],
        ["tx-1"],
    ]
    assert result.batches[0].close_reason == "max_bytes"
    assert not result.rejected


def test_exact_byte_capacity_closes_at_triggering_arrival() -> None:
    config = BatchingConfig(
        max_transactions=10,
        max_raw_bytes=7,
        max_wait_seconds=10,
        length_prefix_bytes=2,
    )
    result = batch_transactions((tx(0, 0.25, b"12345"),), config, flush_time=1)
    assert len(result.batches[0].raw_payload) == 7
    assert result.batches[0].closed_at == 0.25
    assert result.batches[0].close_reason == "max_bytes"


def test_individually_oversized_transaction_is_rejected() -> None:
    config = BatchingConfig(
        max_transactions=10,
        max_raw_bytes=6,
        max_wait_seconds=10,
        length_prefix_bytes=2,
    )
    result = batch_transactions((tx(0, 0, b"12345"),), config, flush_time=1)
    assert not result.batches
    assert result.rejected[0].reason == "individually_oversized"


def test_payload_that_cannot_fit_length_prefix_is_rejected() -> None:
    config = BatchingConfig(
        max_transactions=10,
        max_raw_bytes=1000,
        max_wait_seconds=10,
        length_prefix_bytes=1,
    )
    result = batch_transactions((tx(0, 0, b"x" * 256),), config, flush_time=1)
    assert not result.batches
    assert result.rejected[0].reason == "length_prefix_overflow"


def test_wait_limit_closes_at_deadline_not_next_arrival() -> None:
    config = BatchingConfig(max_transactions=10, max_raw_bytes=100, max_wait_seconds=2)
    result = batch_transactions(
        (tx(0, 1.0, b"a"), tx(1, 5.0, b"b")), config, flush_time=6
    )
    assert result.batches[0].closed_at == 3.0
    assert result.batches[0].close_reason == "max_wait"


def test_arrival_exactly_at_timer_deadline_starts_next_batch() -> None:
    config = BatchingConfig(max_transactions=10, max_raw_bytes=100, max_wait_seconds=2)
    result = batch_transactions(
        (tx(0, 1.0, b"a"), tx(1, 3.0, b"b")), config, flush_time=4
    )
    assert [[item.tx_id for item in batch.transactions] for batch in result.batches] == [
        ["tx-0"],
        ["tx-1"],
    ]
    assert result.batches[0].closed_at == 3.0
    assert result.batches[0].close_reason == "max_wait"


def test_transaction_conservation_and_raw_byte_accounting() -> None:
    transactions = tuple(tx(i, i * 0.1, bytes([i + 1]) * 3) for i in range(5))
    config = BatchingConfig(
        max_transactions=2, max_raw_bytes=100, max_wait_seconds=10, length_prefix_bytes=4
    )
    result = batch_transactions(transactions, config, flush_time=1)
    accepted = [item for batch in result.batches for item in batch.transactions]
    assert accepted + [item.transaction for item in result.rejected] == list(transactions)
    assert all(
        len(batch.raw_payload)
        == sum(config.length_prefix_bytes + item.size_bytes for item in batch.transactions)
        for batch in result.batches
    )


def test_conservation_with_interspersed_rejections_has_no_duplicates_or_losses() -> None:
    transactions = (
        tx(0, 0.0, b"a"),
        tx(1, 0.1, b"x" * 20),
        tx(2, 0.2, b"b"),
        tx(3, 0.3, b"y" * 20),
    )
    result = batch_transactions(
        transactions,
        BatchingConfig(
            max_transactions=10,
            max_raw_bytes=10,
            max_wait_seconds=5,
            length_prefix_bytes=2,
        ),
        flush_time=1,
    )
    terminal_ids = [item.tx_id for batch in result.batches for item in batch.transactions]
    terminal_ids += [item.transaction.tx_id for item in result.rejected]
    assert sorted(terminal_ids) == sorted(item.tx_id for item in transactions)
    assert len(terminal_ids) == len(set(terminal_ids))


def test_unordered_arrivals_are_rejected() -> None:
    with pytest.raises(ValueError, match="ordered"):
        batch_transactions(
            (tx(0, 1, b"a"), tx(1, 0, b"b")),
            BatchingConfig(),
        )
