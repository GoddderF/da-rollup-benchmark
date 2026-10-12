"""Strict, versioned configuration models for deterministic experiments."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
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


class ExternalDAProfileName(StrEnum):
    LOW = "low"
    BASE = "base"
    HIGH = "high"


class WorkloadConfig(StrictModel):
    """Illustrative synthetic workload settings; not empirical network data."""

    arrival_process: ArrivalProcess = ArrivalProcess.POISSON
    arrival_rate_tps: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 10.0
    duration_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 60.0
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)] = 6019
    max_transactions: Annotated[int | None, Field(gt=0)] = None
    size_distribution: SizeDistribution = SizeDistribution.FIXED
    fixed_size_bytes: Annotated[int, Field(gt=0)] = 200
    categorical_sizes_bytes: tuple[int, ...] = ()
    categorical_weights: tuple[Annotated[float, Field(gt=0, allow_inf_nan=False)], ...] = ()
    content_model: ContentModel = ContentModel.HIGH_ENTROPY
    zero_probability: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.0
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
    max_wait_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 2.0
    length_prefix_bytes: Literal[1, 2, 4, 8] = 4


class EthereumConfig(StrictModel):
    profile: EthereumGasProfile = EthereumGasProfile.EIP_7623
    execution_gas_used: Annotated[int, Field(ge=0)] = 0
    effective_gas_price_wei: Annotated[int, Field(ge=0)] = 1_000_000_000
    block_interval_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 12.0
    da_gas_budget_per_block: Annotated[int, Field(gt=0)] = 30_000_000


class CompressionConfig(StrictModel):
    algorithm: Literal["zlib"] = "zlib"
    level: Annotated[int, Field(ge=-1, le=9)] = 6


class TrustAssumptions(StrictModel):
    """Qualitative labels; deliberately not converted into a security score."""

    operator_model: str
    data_availability_guarantee: str
    settlement_relationship: str
    notes: str

    @model_validator(mode="after")
    def reject_blank_labels(self) -> "TrustAssumptions":
        if any(not value.strip() for value in self.model_dump().values()):
            raise ValueError("trust assumption labels must not be blank")
        return self


class ExternalDAConfig(StrictModel):
    """Illustrative mock DA parameters; no profile represents a real network."""

    profile_name: ExternalDAProfileName = ExternalDAProfileName.BASE
    mock_currency_unit: Literal["MOCK_DA_UNIT"] = "MOCK_DA_UNIT"
    fixed_fee: Annotated[Decimal, Field(ge=0)] = Decimal("0.001")
    per_byte_fee: Annotated[Decimal, Field(ge=0)] = Decimal("0.000001")
    bandwidth_bytes_per_second: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 1_000_000.0
    fixed_service_time_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.05
    max_payload_bytes: Annotated[int, Field(gt=0)] = 1_000_000
    queue_capacity_requests: Annotated[int, Field(gt=0)] = 1_000
    service_concurrency: Annotated[int, Field(gt=0)] = 4
    availability_probability: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.999
    availability_seed: Annotated[int, Field(ge=0, le=2**63 - 1)] = 6019
    max_retries: Annotated[int, Field(ge=0)] = 2
    initial_backoff_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.1
    backoff_multiplier: Annotated[float, Field(ge=1, allow_inf_nan=False)] = 2.0
    trust_assumptions: TrustAssumptions = TrustAssumptions(
        operator_model="generic configured operator set",
        data_availability_guarantee="independent Bernoulli success per attempt",
        settlement_relationship="external to Ethereum; not modeled",
        notes="illustrative mock only; no sampling, slashing, or adversarial correlation",
    )


def external_da_profile(name: ExternalDAProfileName | str) -> ExternalDAConfig:
    """Return a validated generic illustrative profile, never a real-network claim."""

    profile_name = ExternalDAProfileName(name)
    common = {
        "profile_name": profile_name,
        "mock_currency_unit": "MOCK_DA_UNIT",
        "availability_seed": 6019,
        "trust_assumptions": TrustAssumptions(
            operator_model="generic configured operator set",
            data_availability_guarantee="independent Bernoulli success per attempt",
            settlement_relationship="external to Ethereum; not modeled",
            notes="illustrative mock only; no sampling, slashing, or adversarial correlation",
        ),
    }
    presets = {
        ExternalDAProfileName.LOW: dict(
            fixed_fee="0.0005",
            per_byte_fee="0.0000005",
            bandwidth_bytes_per_second=250_000,
            fixed_service_time_seconds=0.10,
            max_payload_bytes=500_000,
            queue_capacity_requests=250,
            service_concurrency=2,
            availability_probability=0.99,
            max_retries=2,
            initial_backoff_seconds=0.2,
            backoff_multiplier=2.0,
        ),
        ExternalDAProfileName.BASE: dict(
            fixed_fee="0.001",
            per_byte_fee="0.000001",
            bandwidth_bytes_per_second=1_000_000,
            fixed_service_time_seconds=0.05,
            max_payload_bytes=1_000_000,
            queue_capacity_requests=1_000,
            service_concurrency=4,
            availability_probability=0.999,
            max_retries=2,
            initial_backoff_seconds=0.1,
            backoff_multiplier=2.0,
        ),
        ExternalDAProfileName.HIGH: dict(
            fixed_fee="0.002",
            per_byte_fee="0.000002",
            bandwidth_bytes_per_second=4_000_000,
            fixed_service_time_seconds=0.02,
            max_payload_bytes=2_000_000,
            queue_capacity_requests=4_000,
            service_concurrency=8,
            availability_probability=0.9999,
            max_retries=3,
            initial_backoff_seconds=0.05,
            backoff_multiplier=1.5,
        ),
    }
    return ExternalDAConfig.model_validate(common | presets[profile_name])


class ProjectConfig(StrictModel):
    schema_version: Literal[1] = 1
    project_id: Literal["SC6019"] = "SC6019"
    workload: WorkloadConfig = WorkloadConfig()
    batching: BatchingConfig = BatchingConfig()
    ethereum: EthereumConfig = EthereumConfig()
    compression: CompressionConfig = CompressionConfig()
    external_da: ExternalDAConfig = ExternalDAConfig()

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
