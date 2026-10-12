"""Deterministic zlib compression followed by Ethereum calldata accounting."""

from __future__ import annotations

import time
import zlib
from dataclasses import dataclass
from decimal import Decimal

from ..config import CompressionConfig, EthereumConfig
from .base import PreparedPublication
from .ethereum_calldata import CalldataGasResult, calculate_calldata_gas


@dataclass(frozen=True, slots=True)
class CompressionCpuMeasurement:
    """Host-dependent diagnostic; never part of deterministic simulated latency."""

    elapsed_seconds: float
    iterations: int
    host_dependent: bool = True


@dataclass(frozen=True, slots=True)
class CompressedCalldataResult:
    publication: PreparedPublication
    gas: CalldataGasResult
    compression_level: int
    zlib_runtime_version: str
    simulated_compression_latency_seconds: float = 0.0

    @property
    def compression_ratio(self) -> float:
        if self.publication.raw_payload_bytes == 0:
            return 0.0 if self.publication.encoded_bytes == 0 else float("inf")
        return self.publication.encoded_bytes / self.publication.raw_payload_bytes


class CompressedCalldataStrategy:
    """Prepare compressed calldata requirements; does not schedule block inclusion."""

    strategy_id = "ethereum_calldata_zlib"

    def __init__(self, compression: CompressionConfig, ethereum: EthereumConfig) -> None:
        self.compression = compression
        self.ethereum = ethereum

    def prepare_detailed(
        self, publication_id: str, raw_payload: bytes
    ) -> CompressedCalldataResult:
        encoded = zlib.compress(raw_payload, level=self.compression.level)
        if zlib.decompress(encoded) != raw_payload:
            raise RuntimeError("zlib round-trip validation failed")
        gas = calculate_calldata_gas(
            encoded,
            profile=self.ethereum.profile,
            execution_gas_used=self.ethereum.execution_gas_used,
            effective_gas_price_wei=self.ethereum.effective_gas_price_wei,
        )
        publication = PreparedPublication(
            strategy_id=self.strategy_id,
            publication_id=publication_id,
            raw_payload_bytes=len(raw_payload),
            encoded_payload=encoded,
            capacity_demand=gas.gas_used,
            capacity_unit="gas",
            monetary_cost=Decimal(gas.cost_wei),
            monetary_cost_unit="wei",
            service_time_seconds=None,
            metadata={
                "algorithm": "zlib",
                "compression_level": self.compression.level,
                "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
                "simulated_compression_latency_seconds": 0.0,
            },
        )
        return CompressedCalldataResult(
            publication=publication,
            gas=gas,
            compression_level=self.compression.level,
            zlib_runtime_version=zlib.ZLIB_RUNTIME_VERSION,
        )

    def prepare(self, publication_id: str, raw_payload: bytes) -> PreparedPublication:
        return self.prepare_detailed(publication_id, raw_payload).publication


def measure_compression_cpu_seconds(
    payload: bytes, *, level: int = 6, iterations: int = 1
) -> CompressionCpuMeasurement:
    """Measure local CPU elapsed time as an explicitly non-simulated diagnostic."""

    if level < -1 or level > 9:
        raise ValueError("zlib level must be between -1 and 9")
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    started = time.perf_counter()
    for _ in range(iterations):
        zlib.compress(payload, level=level)
    return CompressionCpuMeasurement(time.perf_counter() - started, iterations)

