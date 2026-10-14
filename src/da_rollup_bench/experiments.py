"""Paired scenario orchestration, resumable artifacts, and run-level statistics."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from .artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    canonical_hash,
    runtime_versions,
    to_jsonable,
    validate_artifact_directory,
    workload_document,
    write_csv,
    write_json,
)
from .config import ProjectConfig, StrictModel, load_config
from .da.compressed_calldata import CompressedCalldataStrategy
from .da.external_mock import MockExternalDAStrategy
from .da.raw_calldata import RawCalldataStrategy
from .engine import SimulationEngine
from .metrics import assert_cross_strategy_fairness, summarize, validate_result
from .statistics import CI_METHOD, aggregate_run_records, paired_comparisons
from .workload import generate_workload, workload_fingerprint
from .artifacts import persist_run_artifacts


class ExperimentSpec(StrictModel):
    schema_version: Literal[1] = 1
    experiment_id: str
    preset: Literal["development", "final"] = "development"
    base_config: str
    repetitions: int | None = Field(default=None, gt=0)
    strategies: tuple[Literal["raw", "compressed", "mock_external"], ...] = (
        "raw",
        "compressed",
        "mock_external",
    )
    matrix: dict[str, tuple[Any, ...]]

    @model_validator(mode="after")
    def validate_spec(self) -> "ExperimentSpec":
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", self.experiment_id):
            raise ValueError("experiment_id must be lowercase alphanumeric, underscore, or hyphen")
        if not self.strategies or len(set(self.strategies)) != len(self.strategies):
            raise ValueError("strategies must be non-empty and unique")
        if not self.matrix or any(not values for values in self.matrix.values()):
            raise ValueError("matrix paths and value lists must be non-empty")
        return self

    def effective_repetitions(self, preset_override: str | None = None) -> int:
        if preset_override is not None:
            return 10 if preset_override == "development" else 30
        if self.repetitions is not None:
            return self.repetitions
        return 10 if self.preset == "development" else 30


@dataclass(frozen=True, slots=True)
class LoadedExperiment:
    spec: ExperimentSpec
    base_config: ProjectConfig
    source_path: Path


@dataclass(frozen=True, slots=True)
class ExperimentOutcome:
    output_directory: Path
    experiment_fingerprint: str
    run_records: tuple[dict[str, Any], ...]
    executed_runs: int
    resumed_runs: int


def load_experiment(path: str | Path) -> LoadedExperiment:
    source = Path(path).resolve()
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("experiment configuration root must be a mapping")
    spec = ExperimentSpec.model_validate(data)
    base_path = (source.parent / spec.base_config).resolve()
    return LoadedExperiment(spec, load_config(base_path), source)


def _replace_dotted(config: ProjectConfig, overrides: dict[str, Any]) -> ProjectConfig:
    document = config.model_dump(mode="json")
    for dotted_path, value in overrides.items():
        parts = dotted_path.split(".")
        target: Any = document
        for part in parts[:-1]:
            if not isinstance(target, dict) or part not in target:
                raise ValueError(f"unknown matrix path: {dotted_path}")
            target = target[part]
        if not isinstance(target, dict) or parts[-1] not in target:
            raise ValueError(f"unknown matrix path: {dotted_path}")
        target[parts[-1]] = value
    resolved = ProjectConfig.model_validate(document)
    if resolved.workload.duration_seconds > resolved.simulation.measurement_horizon_seconds:
        raise ValueError("workload duration cannot exceed the simulation measurement horizon")
    return resolved


def expand_scenarios(loaded: LoadedExperiment) -> tuple[tuple[str, dict[str, Any], ProjectConfig], ...]:
    paths = sorted(loaded.spec.matrix)
    scenarios = []
    for index, values in enumerate(itertools.product(*(loaded.spec.matrix[path] for path in paths))):
        overrides = dict(zip(paths, values))
        suffix = canonical_hash(overrides)[:8]
        scenario_id = f"scenario-{index:04d}-{suffix}"
        scenarios.append((scenario_id, overrides, _replace_dotted(loaded.base_config, overrides)))
    return tuple(scenarios)


def _derived_repetition_seed(base_seed: int, experiment: str, scenario: str, repetition: int) -> int:
    material = f"sc6019:{base_seed}:{experiment}:{scenario}:{repetition}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") & (2**63 - 1)


def _derived_availability_seed(
    base_seed: int, experiment: str, scenario: str, repetition: int
) -> int:
    """Derive an independent, deterministic external-availability RNG stream."""

    material = (
        f"sc6019:seed-policy-v2:external-availability:{base_seed}:"
        f"{experiment}:{scenario}:{repetition}"
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") & (2**63 - 1)


def _strategy(name: str, config: ProjectConfig):
    if name == "raw":
        return RawCalldataStrategy(config.ethereum)
    if name == "compressed":
        return CompressedCalldataStrategy(config.compression, config.ethereum)
    if name == "mock_external":
        return MockExternalDAStrategy(config.external_da)
    raise ValueError(f"unknown strategy: {name}")


def _experiment_identity(
    loaded: LoadedExperiment, repetitions: int
) -> tuple[str, dict[str, Any]]:
    document = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "seed_derivation_policy": "v2-independent-workload-and-external-availability",
        "experiment_id": loaded.spec.experiment_id,
        "preset": loaded.spec.preset,
        "repetitions": repetitions,
        "strategies": loaded.spec.strategies,
        "matrix": loaded.spec.matrix,
        "base_config": loaded.base_config.model_dump(mode="json"),
    }
    return canonical_hash(document), document


def _load_run_record(directory: Path, identity: dict[str, Any]) -> dict[str, Any]:
    manifest = validate_artifact_directory(directory, identity)
    summary_document = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    return {
        **identity,
        "summary": summary_document["summary"],
        "result_canonical_hash": manifest["result_canonical_hash"],
        "batch_signature_hash": manifest["batch_signature_hash"],
        "artifact_directory": str(directory),
    }


def _write_experiment_tables(directory: Path, records: list[dict[str, Any]]) -> None:
    write_json(
        directory / "runs.json",
        {"schema_version": ARTIFACT_SCHEMA_VERSION, "runs": records},
    )
    run_rows = [
        {
            "scenario_id": record["scenario_id"],
            "repetition": record["repetition"],
            "strategy_id": record["strategy_id"],
            "seed": record["seed"],
            "workload_fingerprint": record["workload_fingerprint"],
            "completed": record["summary"]["completed_total"],
            "failed": record["summary"]["failed_transactions"],
            "rejected": record["summary"]["rejected_transactions"],
            "unfinished": record["summary"]["unfinished_transactions"],
            "primary_throughput_tps": record["summary"]["completed_throughput_tps"],
            "completion_ratio": record["summary"]["completion_ratio"],
            "artifact_directory": record["artifact_directory"],
        }
        for record in records
    ]
    write_csv(directory / "runs.csv", run_rows, list(run_rows[0]) if run_rows else ["scenario_id"])
    aggregate = aggregate_run_records(records)
    paired = paired_comparisons(records)
    write_json(
        directory / "aggregate.json",
        {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "ci_method": CI_METHOD,
            "unit_of_replication": "one complete simulation run",
            "rows": aggregate,
        },
    )
    write_csv(
        directory / "aggregate.csv",
        aggregate,
        list(aggregate[0]) if aggregate else ["scenario_id"],
    )
    write_json(
        directory / "paired_comparisons.json",
        {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "ci_method": CI_METHOD,
            "difference": "left strategy minus right strategy within the same repetition",
            "rows": paired,
        },
    )
    write_csv(
        directory / "paired_comparisons.csv",
        paired,
        list(paired[0]) if paired else ["scenario_id"],
    )


def run_experiment(
    experiment_path: str | Path,
    output_root: str | Path,
    *,
    preset_override: Literal["development", "final"] | None = None,
) -> ExperimentOutcome:
    loaded = load_experiment(experiment_path)
    repetitions = loaded.spec.effective_repetitions(preset_override)
    experiment_fingerprint, identity_document = _experiment_identity(loaded, repetitions)
    root = Path(output_root).resolve() / loaded.spec.experiment_id / experiment_fingerprint[:16]
    root_manifest_path = root / "experiment_manifest.json"
    if root.exists() and any(root.iterdir()) and not root_manifest_path.exists():
        raise ValueError(f"refusing to use nonempty unmanifested experiment directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    root_manifest = to_jsonable({
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "experiment_fingerprint": experiment_fingerprint,
        "resolved_experiment": identity_document,
        "runtime": runtime_versions(Path.cwd()),
        "ci_method": CI_METHOD,
    })
    if root_manifest_path.exists():
        existing = json.loads(root_manifest_path.read_text(encoding="utf-8"))
        identity_fields = (
            "schema_version",
            "experiment_fingerprint",
            "resolved_experiment",
            "ci_method",
        )
        if any(existing.get(field) != root_manifest.get(field) for field in identity_fields):
            raise ValueError("existing experiment manifest is incompatible")
    else:
        write_json(root_manifest_path, root_manifest)

    records: list[dict[str, Any]] = []
    executed = 0
    resumed = 0
    for scenario_id, overrides, scenario_config in expand_scenarios(loaded):
        for repetition in range(repetitions):
            seed = _derived_repetition_seed(
                scenario_config.workload.seed,
                loaded.spec.experiment_id,
                scenario_id,
                repetition,
            )
            config_data = scenario_config.model_dump(mode="json")
            config_data["workload"]["seed"] = seed
            availability_seed = _derived_availability_seed(
                scenario_config.external_da.availability_seed,
                loaded.spec.experiment_id,
                scenario_id,
                repetition,
            )
            config_data["external_da"]["availability_seed"] = availability_seed
            config = ProjectConfig.model_validate(config_data)
            transactions = generate_workload(config.workload)
            fingerprint = workload_fingerprint(transactions)
            repetition_dir = root / scenario_id / f"rep-{repetition:03d}"
            repetition_dir.mkdir(parents=True, exist_ok=True)
            workload_path = repetition_dir / "workload.json"
            workload_manifest_path = repetition_dir / "workload_manifest.json"
            workload_identity = {
                "scenario_id": scenario_id,
                "scenario_overrides": overrides,
                "repetition": repetition,
                "seed": seed,
                "availability_seed": availability_seed,
                "workload_fingerprint": fingerprint,
                "config_fingerprint": config.fingerprint(),
            }
            expected_workload_manifest = {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "identity": workload_identity,
                "workload_canonical_hash": canonical_hash(workload_document(transactions)),
            }
            if workload_manifest_path.exists():
                existing = json.loads(workload_manifest_path.read_text(encoding="utf-8"))
                if existing != expected_workload_manifest:
                    raise ValueError("stored workload is incompatible with requested repetition")
                stored = json.loads(workload_path.read_text(encoding="utf-8"))
                if canonical_hash(stored) != expected_workload_manifest["workload_canonical_hash"]:
                    raise ValueError("stored workload artifact hash mismatch")
            else:
                if workload_path.exists():
                    raise ValueError("unmanifested workload artifact exists")
                write_json(workload_path, workload_document(transactions))
                write_json(workload_manifest_path, expected_workload_manifest)

            repetition_results = []
            repetition_manifests = []
            for strategy_name in loaded.spec.strategies:
                strategy = _strategy(strategy_name, config)
                run_directory = repetition_dir / strategy.strategy_id
                run_identity = {
                    "experiment_fingerprint": experiment_fingerprint,
                    "scenario_id": scenario_id,
                    "scenario_overrides": overrides,
                    "repetition": repetition,
                    "seed": seed,
                    "availability_seed": availability_seed,
                    "strategy_id": strategy.strategy_id,
                    "workload_fingerprint": fingerprint,
                    "config_fingerprint": config.fingerprint(),
                }
                if (run_directory / "manifest.json").exists():
                    record = _load_run_record(run_directory, run_identity)
                    resumed += 1
                    records.append(record)
                    repetition_manifests.append(
                        validate_artifact_directory(run_directory, run_identity)
                    )
                    continue

                result = SimulationEngine(
                    batching=config.batching,
                    strategy=strategy,
                    ethereum=config.ethereum,
                    external_da=config.external_da,
                    simulation=config.simulation,
                ).run(transactions)
                validation = validate_result(
                    result,
                    transactions,
                    ethereum=config.ethereum,
                    external_da=config.external_da,
                )
                if not validation.valid:
                    raise RuntimeError("simulation invariant validation failed")
                summary = summarize(result)
                manifest = persist_run_artifacts(
                    run_directory,
                    identity=run_identity,
                    config=config,
                    transactions=transactions,
                    result=result,
                    summary=summary,
                    validation=validation,
                    repository=Path.cwd(),
                )
                repetition_results.append(result)
                repetition_manifests.append(manifest)
                records.append(
                    {
                        **run_identity,
                        "summary": to_jsonable(summary),
                        "result_canonical_hash": manifest["result_canonical_hash"],
                        "batch_signature_hash": manifest["batch_signature_hash"],
                        "artifact_directory": str(run_directory),
                    }
                )
                executed += 1
            if len(repetition_results) > 1:
                assert_cross_strategy_fairness(repetition_results)
            if len({item["batch_signature_hash"] for item in repetition_manifests}) != 1:
                raise RuntimeError("cross-strategy batch signature mismatch")

    records.sort(key=lambda item: (item["scenario_id"], item["repetition"], item["strategy_id"]))
    _write_experiment_tables(root, records)
    return ExperimentOutcome(root, experiment_fingerprint, tuple(records), executed, resumed)


def validate_experiment_artifacts(directory: str | Path) -> int:
    root = Path(directory).resolve()
    manifest = json.loads((root / "experiment_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported experiment manifest schema")
    runs = json.loads((root / "runs.json").read_text(encoding="utf-8"))["runs"]
    for record in runs:
        identity_keys = [
            "experiment_fingerprint",
            "scenario_id",
            "scenario_overrides",
            "repetition",
            "seed",
            "strategy_id",
            "workload_fingerprint",
            "config_fingerprint",
        ]
        if "availability_seed" in record:
            identity_keys.append("availability_seed")
        identity = {key: record[key] for key in identity_keys}
        validate_artifact_directory(Path(record["artifact_directory"]), identity)
    return len(runs)


def resummarize_experiment(directory: str | Path) -> int:
    root = Path(directory).resolve()
    runs = json.loads((root / "runs.json").read_text(encoding="utf-8"))["runs"]
    _write_experiment_tables(root, runs)
    return len(runs)
