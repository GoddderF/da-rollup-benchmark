"""Thin scheduling-neutral wrapper for uncompressed Ethereum calldata."""

from __future__ import annotations

from decimal import Decimal

from ..config import EthereumConfig
from .base import PreparedPublication
from .ethereum_calldata import calculate_calldata_gas


class RawCalldataStrategy:
    strategy_id = "ethereum_calldata_raw"

    def __init__(self, ethereum: EthereumConfig) -> None:
        self.ethereum = ethereum

    def prepare(self, publication_id: str, raw_payload: bytes) -> PreparedPublication:
        gas = calculate_calldata_gas(
            raw_payload,
            profile=self.ethereum.profile,
            execution_gas_used=self.ethereum.execution_gas_used,
            effective_gas_price_wei=self.ethereum.effective_gas_price_wei,
        )
        return PreparedPublication(
            strategy_id=self.strategy_id,
            publication_id=publication_id,
            raw_payload_bytes=len(raw_payload),
            encoded_payload=raw_payload,
            capacity_demand=gas.gas_used,
            capacity_unit="gas",
            monetary_cost=Decimal(gas.cost_wei),
            monetary_cost_unit="wei",
            service_time_seconds=None,
            metadata={
                "profile": gas.profile.value,
                "zero_bytes": gas.zero_bytes,
                "nonzero_bytes": gas.nonzero_bytes,
                "calldata_tokens": gas.calldata_tokens,
            },
        )
