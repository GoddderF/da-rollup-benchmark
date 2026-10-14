import json
from pathlib import Path

import pandas as pd
import pytest

from da_rollup_bench.dashboard_data import (
    discover_experiment_listings,
    discover_experiments,
    downloadable_csv,
    load_experiment,
    metric_table,
    preferred_experiment_index,
    ratio_table,
)


def write_artifacts(
    root: Path,
    *,
    offered: int = 2,
    experiment_id: str = "transaction-load-sweep",
    repetitions: int = 1,
    seed_policy: str | None = None,
) -> Path:
    run_dir = root / "scenario" / "rep" / "raw"
    run_dir.mkdir(parents=True)
    (run_dir / "config.json").write_text(json.dumps({"schema_version": 1, "external_da": {}}))
    resolved = {"experiment_id": experiment_id, "repetitions": repetitions}
    if seed_policy is not None:
        resolved["seed_derivation_policy"] = seed_policy
    manifest = {"schema_version": 1, "experiment_fingerprint": "abc", "resolved_experiment": resolved}
    run = {
        "scenario_id": "s1", "scenario_overrides": {"workload.arrival_rate_tps": 2},
        "repetition": 0, "strategy_id": "ethereum_calldata_raw", "workload_fingerprint": "w",
        "artifact_directory": str(run_dir),
        "summary": {"offered_transactions": offered, "completed_total": 1,
                    "failed_transactions": 0, "rejected_transactions": 1,
                    "unfinished_transactions": 0},
    }
    aggregate = [{"scenario_id": "s1", "strategy_id": "ethereum_calldata_raw",
                  "metric": "completed_total", "n": 1, "mean": 1,
                  "ci95_low": None, "ci95_high": None}]
    for name, document in {
        "experiment_manifest.json": manifest,
        "runs.json": {"schema_version": 1, "runs": [run]},
        "aggregate.json": {"schema_version": 1, "rows": aggregate},
        "paired_comparisons.json": {"schema_version": 1, "rows": []},
    }.items():
        if "schema_version" not in document:
            document["schema_version"] = 1
        (root / name).write_text(json.dumps(document), encoding="utf-8")
    return root


def test_discovery_loading_and_metric_labels(tmp_path: Path) -> None:
    directory = write_artifacts(tmp_path / "experiment")
    assert discover_experiments(tmp_path) == (directory.resolve(),)
    loaded = load_experiment(directory)
    table = metric_table(loaded, ["completed_total"])
    assert table.iloc[0]["strategy"] == "Raw calldata"
    assert "arrival_rate_tps=2" in table.iloc[0]["scenario"]


def test_ratios_and_csv_are_stable(tmp_path: Path) -> None:
    loaded = load_experiment(write_artifacts(tmp_path / "experiment"))
    ratios = ratio_table(loaded, ["ethereum_calldata_raw"])
    assert ratios.iloc[0]["completed_ratio"] == 0.5
    assert ratios.iloc[0]["rejected_ratio"] == 0.5
    assert downloadable_csv(pd.DataFrame([{"a": 1}])) == b"a\n1\n"


def test_zero_offers_and_missing_metrics_are_safe(tmp_path: Path) -> None:
    loaded = load_experiment(write_artifacts(tmp_path / "experiment", offered=0))
    assert pd.isna(ratio_table(loaded, ["ethereum_calldata_raw"]).iloc[0]["completed_ratio"])
    assert metric_table(loaded, ["missing"]).empty


def test_invalid_schema_is_rejected(tmp_path: Path) -> None:
    directory = write_artifacts(tmp_path / "experiment")
    (directory / "aggregate.json").write_text(json.dumps({"schema_version": 99, "rows": []}))
    with pytest.raises(ValueError, match="unsupported artifact schema"):
        load_experiment(directory)


def test_final_validated_experiments_are_distinct_and_preferred(tmp_path: Path) -> None:
    policy = "v2-independent-workload-and-external-availability"
    names = (
        "transaction-load-sweep",
        "batch-size-sweep",
        "data-compressibility-sweep",
        "external-da-sensitivity",
    )
    for name in names:
        write_artifacts(
            tmp_path / "final-validated" / name / f"final-{name}",
            experiment_id=name,
            repetitions=30,
            seed_policy=policy,
        )
    write_artifacts(
        tmp_path / "milestone10-review" / "transaction-load-sweep" / "development",
        experiment_id="transaction-load-sweep",
        repetitions=10,
    )
    write_artifacts(
        tmp_path / "final" / "transaction-load-sweep" / "superseded",
        experiment_id="transaction-load-sweep",
        repetitions=30,
        seed_policy=policy,
    )

    listings = discover_experiment_listings(tmp_path)
    final = [item for item in listings if item.category == "FINAL-VALIDATED"]
    assert {item.experiment_id for item in final} == set(names)
    assert len({item.label for item in listings}) == len(listings)
    assert "DEVELOPMENT" in {item.category for item in listings}
    assert "SUPERSEDED" in {item.category for item in listings}
    selected = listings[preferred_experiment_index(listings)]
    assert selected.category == "FINAL-VALIDATED"
    assert selected.experiment_id == "transaction-load-sweep"


def test_discovery_is_uncached_and_sees_new_or_replaced_manifests(tmp_path: Path) -> None:
    first = write_artifacts(tmp_path / "development" / "one", experiment_id="one")
    initial = discover_experiment_listings(tmp_path)
    assert [item.experiment_id for item in initial] == ["one"]

    write_artifacts(tmp_path / "development" / "two", experiment_id="two")
    refreshed = discover_experiment_listings(tmp_path)
    assert {item.experiment_id for item in refreshed} == {"one", "two"}

    manifest_path = first / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["resolved_experiment"]["repetitions"] = 7
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    replaced = discover_experiment_listings(tmp_path)
    one = next(item for item in replaced if item.experiment_id == "one")
    assert one.repetitions == 7
    assert "7 reps" in one.label


def test_incompatible_manifest_is_reported_without_breaking_discovery(tmp_path: Path) -> None:
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "experiment_manifest.json").write_text("{not json", encoding="utf-8")
    listing = discover_experiment_listings(tmp_path)[0]
    assert not listing.compatible
    assert listing.category == "INCOMPATIBLE"
    assert listing.error
