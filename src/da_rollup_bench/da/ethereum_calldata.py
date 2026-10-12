"""Ethereum calldata gas accounting for a deliberately narrow transaction scope.

Supported transaction: ordinary, non-contract-creation transaction with no access
list, authorization list, initcode, or blob fields. ``execution_gas_used`` is EVM
execution gas after refunds. Formulas follow EIP-2028 and EIP-7623.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import EthereumGasProfile

TRANSACTION_BASE_GAS = 21_000
STANDARD_TOKEN_COST = 4
TOTAL_COST_FLOOR_PER_TOKEN = 10


@dataclass(frozen=True, slots=True)
class CalldataGasResult:
    profile: EthereumGasProfile
    calldata_bytes: int
    zero_bytes: int
    nonzero_bytes: int
    calldata_tokens: int
    standard_calldata_gas: int
    execution_gas_used: int
    transaction_floor_gas: int
    floor_increment_gas: int
    gas_used: int
    effective_gas_price_wei: int
    cost_wei: int

    @property
    def cost_eth(self) -> float:
        return self.cost_wei / 10**18


def calculate_calldata_gas(
    calldata: bytes,
    *,
    profile: EthereumGasProfile = EthereumGasProfile.EIP_7623,
    execution_gas_used: int = 0,
    effective_gas_price_wei: int = 0,
) -> CalldataGasResult:
    """Calculate gas used and cost for the supported publication transaction.

    EIP-2028: ``21000 + 4*T + execution_gas_used``.
    EIP-7623: ``21000 + max(4*T + execution_gas_used, 10*T)``.
    Here ``T = zero_bytes + 4*nonzero_bytes``.
    """

    if execution_gas_used < 0:
        raise ValueError("execution_gas_used must be non-negative")
    if effective_gas_price_wei < 0:
        raise ValueError("effective_gas_price_wei must be non-negative")
    profile = EthereumGasProfile(profile)

    zero_bytes = calldata.count(0)
    nonzero_bytes = len(calldata) - zero_bytes
    tokens = zero_bytes + 4 * nonzero_bytes
    standard_calldata_gas = STANDARD_TOKEN_COST * tokens
    ordinary_inner_gas = standard_calldata_gas + execution_gas_used
    floor_inner_gas = TOTAL_COST_FLOOR_PER_TOKEN * tokens

    if profile == EthereumGasProfile.EIP_7623:
        charged_inner_gas = max(ordinary_inner_gas, floor_inner_gas)
        floor_increment_gas = max(0, floor_inner_gas - ordinary_inner_gas)
    else:
        charged_inner_gas = ordinary_inner_gas
        floor_increment_gas = 0

    gas_used = TRANSACTION_BASE_GAS + charged_inner_gas
    return CalldataGasResult(
        profile=profile,
        calldata_bytes=len(calldata),
        zero_bytes=zero_bytes,
        nonzero_bytes=nonzero_bytes,
        calldata_tokens=tokens,
        standard_calldata_gas=standard_calldata_gas,
        execution_gas_used=execution_gas_used,
        transaction_floor_gas=TRANSACTION_BASE_GAS + floor_inner_gas,
        floor_increment_gas=floor_increment_gas,
        gas_used=gas_used,
        effective_gas_price_wei=effective_gas_price_wei,
        cost_wei=gas_used * effective_gas_price_wei,
    )

