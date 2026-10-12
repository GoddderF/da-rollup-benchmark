from pathlib import Path

import pytest
from pydantic import ValidationError

from da_rollup_bench.config import (
    EthereumGasProfile,
    ProjectConfig,
    SizeDistribution,
    WorkloadConfig,
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

