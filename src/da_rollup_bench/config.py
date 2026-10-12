"""Strict, versioned configuration models for deterministic experiments."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects misspelled/unknown configuration keys."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ArrivalProcess(StrEnum):
    FIXED = "fixed"
    POISSON = "poisson"


class SizeDistribution(StrEnum):
    FIXED = "fixed"
    CATEGORICAL = "categorical"


class ContentModel(StrEnum):
    HIGH_ENTROPY = "high_entropy"
    ZERO_FRACTION = "zero_fraction"
    REPEATED = "repeated"


class EthereumGasProfile(StrEnum):
    EIP_2028 = "eip_2028"
    EIP_7623 = "eip_7623"


class WorkloadConfig(StrictModel):
    """Illustrative synthetic workload settings; not empirical network data."""

    arrival_process: ArrivalProcess = ArrivalProcess.POISSON
    arrival_rate_tps: Annotated[float, Field(gt=0)] = 10.0
    duration_seconds: Annotated[float, Field(gt=0)] = 60.0
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)] = 6019
    max_transactions: Annotated[int | None, Field(gt=0)] = None
    size_distribution: SizeDistribution = SizeDistribution.FIXED
    fixed_size_bytes: Annotated[int, Field(gt=0)] = 200
    categorical_sizes_bytes: tuple[int, ...] = ()
    categorical_weights: tuple[float, ...] = ()
    content_model: ContentModel = ContentModel.HIGH_ENTROPY
    zero_probability: Annotated[float, Field(ge=0, le=1)] = 0.0
    repeated_pattern_hex: str = "534336303139"  # ASCII: SC6019

    @model_validator(mode="after")
    def validate_distribution_and_content(self) -> "WorkloadConfig":
        if self.size_distribution == SizeDistribution.CATEGORICAL:
            if not self.categorical_sizes_bytes:
                raise ValueError("categorical sizes must not be empty")
            if len(self.categorical_sizes_bytes) != len(self.categorical_weights):
                raise ValueError("categorical sizes and weights must have equal lengths")
            if any(size <= 0 for size in self.categorical_sizes_bytes):
                raise ValueError("categorical sizes must be positive")
            if any(weight <= 0 for weight in self.categorical_weights):
                raise ValueError("categorical weights must be positive")
        if self.content_model == ContentModel.REPEATED:
            try:
                pattern = bytes.fromhex(self.repeated_pattern_hex)
            except ValueError as exc:
                raise ValueError("repeated_pattern_hex must be valid hexadecimal") from exc
            if not pattern:
                raise ValueError("repeated pattern must not be empty")
        return self


class BatchingConfig(StrictModel):
    max_transactions: Annotated[int, Field(gt=0)] = 100
    max_raw_bytes: Annotated[int, Field(gt=0)] = 128_000
    max_wait_seconds: Annotated[float, Field(gt=0)] = 2.0
    length_prefix_bytes: Literal[1, 2, 4, 8] = 4


class EthereumConfig(StrictModel):
    profile: EthereumGasProfile = EthereumGasProfile.EIP_7623
    execution_gas_used: Annotated[int, Field(ge=0)] = 0
    effective_gas_price_wei: Annotated[int, Field(ge=0)] = 1_000_000_000
    block_interval_seconds: Annotated[float, Field(gt=0)] = 12.0
    da_gas_budget_per_block: Annotated[int, Field(gt=0)] = 30_000_000


class ProjectConfig(StrictModel):
    schema_version: Literal[1] = 1
    project_id: Literal["SC6019"] = "SC6019"
    workload: WorkloadConfig = WorkloadConfig()
    batching: BatchingConfig = BatchingConfig()
    ethereum: EthereumConfig = EthereumConfig()

    def canonical_json(self) -> str:
        """Return stable JSON suitable for manifests and hashing."""

        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def load_config(path: str | Path) -> ProjectConfig:
    """Load and strictly validate a YAML configuration file."""

    with Path(path).open("r", encoding="utf-8") as stream:
        data = yaml.safe_load(stream)
    if not isinstance(data, dict):
        raise ValueError("configuration root must be a mapping")
    return ProjectConfig.model_validate(data)

