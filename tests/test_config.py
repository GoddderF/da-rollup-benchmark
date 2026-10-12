import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from da_rollup_bench.config import (
    EthereumGasProfile,
    ExternalDAProfileName,
    ProjectConfig,
    SizeDistribution,
    WorkloadConfig,
    external_da_profile,
    load_config,
)


def test_defaults_are_versioned_and_use_approved_identity_and_profile() -> None:
    config = ProjectConfig()
    assert config.schema_version == 1
    assert config.project_id == "SC6019"
    assert config.ethereum.profile == EthereumGasProfile.EIP_7623


def test_baseline_yaml_loads_and_has_stable_fingerprint() -> None:
    path = Path(__file__).parents[1] / "configs" / "baseline.yaml"
    first = load_config(path)
    second = load_config(path)
    assert first == second
    assert first.fingerprint() == second.fingerprint()
    assert len(first.fingerprint()) == 64
    assert first.fingerprint() == "a742bffb611f85e0607fc358cec733173dd2da9076d256ca0552e0ed827da76c"


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProjectConfig.model_validate({"workload": {"arrival_rates_tps": 10}})


@pytest.mark.parametrize("rate", [0, -1])
def test_non_positive_arrival_rate_is_rejected(rate: float) -> None:
    with pytest.raises(ValidationError):
        WorkloadConfig(arrival_rate_tps=rate)


def test_categorical_distribution_requires_matching_positive_weights() -> None:
    with pytest.raises(ValidationError, match="equal lengths"):
        WorkloadConfig(
            size_distribution=SizeDistribution.CATEGORICAL,
            categorical_sizes_bytes=(100, 200),
            categorical_weights=(1.0,),
        )


def test_configuration_is_immutable() -> None:
    config = ProjectConfig()
    with pytest.raises(ValidationError):
        config.workload.seed = 7  # type: ignore[misc]


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_non_finite_rates_are_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        WorkloadConfig(arrival_rate_tps=value)


def test_generic_external_da_profiles_are_distinct_and_explicitly_mock() -> None:
    low = external_da_profile(ExternalDAProfileName.LOW)
    base = external_da_profile(ExternalDAProfileName.BASE)
    high = external_da_profile(ExternalDAProfileName.HIGH)
    assert {low.profile_name, base.profile_name, high.profile_name} == set(ExternalDAProfileName)
    assert {low.mock_currency_unit, base.mock_currency_unit, high.mock_currency_unit} == {
        "MOCK_DA_UNIT"
    }
    assert low.bandwidth_bytes_per_second < base.bandwidth_bytes_per_second < high.bandwidth_bytes_per_second
