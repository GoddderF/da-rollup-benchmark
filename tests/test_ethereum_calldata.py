import pytest

from da_rollup_bench.config import EthereumGasProfile
from da_rollup_bench.da.ethereum_calldata import calculate_calldata_gas


@pytest.mark.parametrize(
    ("calldata", "execution_gas", "expected_2028", "expected_7623"),
    [
        (b"", 0, 21_000, 21_000),
        (b"\x00", 0, 21_004, 21_010),
        (b"\xff", 0, 21_016, 21_040),
        (b"\x00\xff", 0, 21_020, 21_050),
        (b"\xff", 24, 21_040, 21_040),
        (b"\xff", 25, 21_041, 21_041),
    ],
)
def test_official_formula_hand_calculated_golden_vectors(
    calldata: bytes,
    execution_gas: int,
    expected_2028: int,
    expected_7623: int,
) -> None:
    legacy = calculate_calldata_gas(
        calldata, profile=EthereumGasProfile.EIP_2028, execution_gas_used=execution_gas
    )
    floor = calculate_calldata_gas(
        calldata, profile=EthereumGasProfile.EIP_7623, execution_gas_used=execution_gas
    )
    assert legacy.gas_used == expected_2028
    assert floor.gas_used == expected_7623


def test_byte_and_token_accounting() -> None:
    result = calculate_calldata_gas(b"\x00\x01\x00\xff")
    assert result.calldata_bytes == 4
    assert result.zero_bytes == 2
    assert result.nonzero_bytes == 2
    assert result.calldata_tokens == 10
    assert result.standard_calldata_gas == 40
    assert result.transaction_floor_gas == 21_100
    assert result.floor_increment_gas == 60


def test_cost_units_are_integer_wei_and_explicit_eth_conversion() -> None:
    result = calculate_calldata_gas(b"\xff", effective_gas_price_wei=2_000_000_000)
    assert result.cost_wei == 21_040 * 2_000_000_000
    assert result.cost_eth == pytest.approx(0.00004208)


@pytest.mark.parametrize(
    ("field", "value"), [("execution_gas_used", -1), ("effective_gas_price_wei", -1)]
)
def test_negative_inputs_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        calculate_calldata_gas(b"", **{field: value})


def test_profile_string_is_validated() -> None:
    with pytest.raises(ValueError):
        calculate_calldata_gas(b"", profile="unknown")  # type: ignore[arg-type]

