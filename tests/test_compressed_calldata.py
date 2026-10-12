import zlib

import pytest

from da_rollup_bench.config import CompressionConfig, EthereumConfig, EthereumGasProfile
from da_rollup_bench.da.compressed_calldata import (
    CompressedCalldataStrategy,
    measure_compression_cpu_seconds,
)


@pytest.mark.parametrize(
    "payload",
    [bytes(range(256)) * 4, bytes(1024), b"SC6019" * 200, b""],
    ids=["high-entropy-like", "zero-heavy", "repeated", "empty"],
)
def test_compression_round_trip_and_actual_encoded_accounting(payload: bytes) -> None:
    strategy = CompressedCalldataStrategy(
        CompressionConfig(level=6),
        EthereumConfig(profile=EthereumGasProfile.EIP_7623, effective_gas_price_wei=7),
    )
    result = strategy.prepare_detailed("batch-1", payload)
    encoded = result.publication.encoded_payload
    assert zlib.decompress(encoded) == payload
    assert result.publication.raw_payload_bytes == len(payload)
    assert result.publication.encoded_bytes == len(encoded)
    assert result.gas.calldata_bytes == len(encoded)
    assert result.gas.zero_bytes + result.gas.nonzero_bytes == len(encoded)

    tokens = result.gas.zero_bytes + 4 * result.gas.nonzero_bytes
    expected_gas = 21_000 + max(4 * tokens, 10 * tokens)
    assert result.gas.gas_used == expected_gas
    assert result.publication.capacity_demand == expected_gas
    assert result.publication.monetary_cost == expected_gas * 7


def test_repeated_and_zero_payloads_compress_below_raw_size() -> None:
    strategy = CompressedCalldataStrategy(CompressionConfig(), EthereumConfig())
    assert strategy.prepare("zero", bytes(4096)).encoded_bytes < 4096
    assert strategy.prepare("repeat", b"abc123" * 1000).encoded_bytes < 6000


def test_empty_payload_has_real_zlib_envelope_and_valid_gas_accounting() -> None:
    result = CompressedCalldataStrategy(CompressionConfig(), EthereumConfig()).prepare_detailed(
        "empty", b""
    )
    assert result.publication.encoded_payload == zlib.compress(b"", level=6)
    assert result.publication.encoded_bytes > 0
    assert result.gas.gas_used > 21_000


def test_host_cpu_measurement_is_separate_from_simulated_latency() -> None:
    strategy = CompressedCalldataStrategy(CompressionConfig(), EthereumConfig())
    result = strategy.prepare_detailed("batch", b"payload" * 100)
    diagnostic = measure_compression_cpu_seconds(b"payload" * 100, iterations=2)
    assert result.simulated_compression_latency_seconds == 0
    assert result.publication.metadata["simulated_compression_latency_seconds"] == 0
    assert result.publication.service_time_seconds is None
    assert diagnostic.host_dependent is True
    assert diagnostic.iterations == 2
    assert diagnostic.elapsed_seconds >= 0


@pytest.mark.parametrize("iterations", [0, -1])
def test_cpu_measurement_rejects_invalid_iterations(iterations: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        measure_compression_cpu_seconds(b"x", iterations=iterations)

