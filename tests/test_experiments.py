import json
from pathlib import Path

import pytest
import yaml

from da_rollup_bench.cli import main
from da_rollup_bench.config import (
    ArrivalProcess,
    BatchingConfig,
    EthereumConfig,
    ExternalDAConfig,
    ProjectConfig,
    SimulationConfig,
    WorkloadConfig,
)
from da_rollup_bench.experiments import (
    expand_scenarios,
    load_experiment,
    run_experiment,
    validate_experiment_artifacts,
)


def write_small_configs(tmp_path: Path, *, repetitions: int = 2) -> Path:
    project = ProjectConfig(
        workload=WorkloadConfig(
            arrival_process=ArrivalProcess.FIXED,
            arrival_rate_tps=2,
            duration_seconds=2,
            fixed_size_bytes=8,
            seed=11,
        ),
        batching=BatchingConfig(max_transactions=2, max_raw_bytes=100, max_wait_seconds=1),
        ethereum=EthereumConfig(
            effective_gas_price_wei=2,
            block_interval_seconds=1,
            da_gas_budget_per_block=1_000_000,
        ),
        external_da=ExternalDAConfig(
            availability_probability=1,
            bandwidth_bytes_per_second=1_000,
            fixed_service_time_seconds=0.01,
        ),
        simulation=SimulationConfig(measurement_horizon_seconds=3),
    )
    project_path = tmp_path / "project.yaml"
    project_path.write_text(
        yaml.safe_dump(project.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    experiment_path = tmp_path / "experiment.yaml"
    experiment_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "experiment_id": "small-paired",
                "preset": "development",
                "base_config": "project.yaml",
                "repetitions": repetitions,
                "strategies": ["raw", "compressed", "mock_external"],
                "matrix": {"workload.arrival_rate_tps": [2.0]},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return experiment_path


def test_paired_experiment_artifacts_statistics_and_resume(tmp_path: Path) -> None:
    experiment = write_small_configs(tmp_path)
    output_root = tmp_path / "outputs"
    first = run_experiment(experiment, output_root)
    assert first.executed_runs == 6
    assert first.resumed_runs == 0
    assert len(first.run_records) == 6
    availability_by_repetition = {
        repetition: {
            record["availability_seed"]
            for record in first.run_records
            if record["repetition"] == repetition
        }
        for repetition in range(2)
    }
    assert all(len(seeds) == 1 for seeds in availability_by_repetition.values())
    assert availability_by_repetition[0] != availability_by_repetition[1]
    assert validate_experiment_artifacts(first.output_directory) == 6
    required = {
        "experiment_manifest.json",
        "runs.json",
        "runs.csv",
        "aggregate.json",
        "aggregate.csv",
        "paired_comparisons.json",
        "paired_comparisons.csv",
    }
    assert required <= {path.name for path in first.output_directory.iterdir()}
    before_runs = (first.output_directory / "runs.json").read_bytes()
    hashes = [record["result_canonical_hash"] for record in first.run_records]

    second = run_experiment(experiment, output_root)
    assert second.executed_runs == 0
    assert second.resumed_runs == 6
    assert [record["result_canonical_hash"] for record in second.run_records] == hashes
    assert (second.output_directory / "runs.json").read_bytes() == before_runs

    aggregate = json.loads((first.output_directory / "aggregate.json").read_text())
    throughput_rows = [
        row for row in aggregate["rows"] if row["metric"] == "completed_throughput_tps"
    ]
    assert throughput_rows and all(row["n"] == 2 for row in throughput_rows)
    assert aggregate["unit_of_replication"] == "one complete simulation run"


def test_resume_rejects_incompatible_run_manifest(tmp_path: Path) -> None:
    experiment = write_small_configs(tmp_path, repetitions=1)
    first = run_experiment(experiment, tmp_path / "outputs")
    run_directory = Path(first.run_records[0]["artifact_directory"])
    manifest_path = run_directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["identity"]["seed"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="incompatible"):
        run_experiment(experiment, tmp_path / "outputs")


def test_resume_tolerates_runtime_metadata_lookup_changes(tmp_path: Path) -> None:
    experiment = write_small_configs(tmp_path, repetitions=1)
    first = run_experiment(experiment, tmp_path / "outputs")
    manifest_path = first.output_directory / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime"]["code_revision"] = None
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    resumed = run_experiment(experiment, tmp_path / "outputs")
    assert resumed.executed_runs == 0
    assert resumed.resumed_runs == 3


def test_primary_experiment_configs_expand(tmp_path: Path) -> None:
    root = Path(__file__).parents[1] / "configs" / "experiments"
    expected = {
        "transaction_load_sweep.yaml": 3,
        "batch_size_sweep.yaml": 3,
        "data_compressibility_sweep.yaml": 3,
        "external_da_sensitivity.yaml": 8,
    }
    for name, count in expected.items():
        assert len(expand_scenarios(load_experiment(root / name))) == count


def test_cli_validation_workload_and_single_run(tmp_path: Path, capsys) -> None:
    experiment = write_small_configs(tmp_path, repetitions=1)
    project = tmp_path / "project.yaml"
    assert main(["validate-config", str(project)]) == 0
    workload = tmp_path / "workload.json"
    assert main(["generate-workload", str(project), "--output", str(workload)]) == 0
    assert workload.exists()
    run_dir = tmp_path / "single"
    assert main(
        [
            "run-single",
            str(project),
            "--strategy",
            "raw",
            "--output-dir",
            str(run_dir),
        ]
    ) == 0
    assert main(["validate-artifacts", str(run_dir)]) == 0
    assert main(["validate-config", str(experiment), "--kind", "experiment"]) == 0
    assert "valid" in capsys.readouterr().out

