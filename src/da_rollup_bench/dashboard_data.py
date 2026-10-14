"""Read-only loading and presentation transforms for Milestone 10 artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .artifacts import ARTIFACT_SCHEMA_VERSION


STRATEGY_LABELS = {
    "ethereum_calldata_raw": "Raw calldata",
    "ethereum_calldata_zlib": "Compressed calldata",
    "mock_external_da": "Mock external DA",
}


@dataclass(frozen=True)
class DashboardExperiment:
    root: Path
    manifest: dict[str, Any]
    runs: pd.DataFrame
    aggregate: pd.DataFrame
    paired: pd.DataFrame
    scenario_overrides: dict[str, dict[str, Any]]
    sample_config: dict[str, Any] | None


@dataclass(frozen=True)
class ExperimentListing:
    """Small manifest-only description used by the experiment selector."""

    root: Path
    label: str
    category: str
    experiment_id: str
    repetitions: int | None
    experiment_fingerprint: str | None
    compatible: bool
    error: str | None = None


def discover_experiments(results_root: str | Path) -> tuple[Path, ...]:
    """Backward-compatible path discovery.

    Discovery is intentionally uncached: a Streamlit rerun must see manifests
    created or replaced while the dashboard is open.
    """

    return tuple(item.root for item in discover_experiment_listings(results_root))


def _lineage_category(directory: Path, manifest: dict[str, Any]) -> str:
    parts = {part.casefold() for part in directory.parts}
    resolved = manifest.get("resolved_experiment", {})
    repetitions = resolved.get("repetitions") if isinstance(resolved, dict) else None
    seed_policy = resolved.get("seed_derivation_policy") if isinstance(resolved, dict) else None
    if "final-validated" in parts:
        if repetitions == 30 and seed_policy == "v2-independent-workload-and-external-availability":
            return "FINAL-VALIDATED"
        return "FINAL-VALIDATED (metadata warning)"
    if "final" in parts:
        return "SUPERSEDED"
    if "milestone10-review" in parts or (isinstance(repetitions, int) and repetitions < 30):
        return "DEVELOPMENT"
    return "OTHER"


def _listing_label(
    category: str,
    experiment_id: str,
    repetitions: int | None,
    directory: Path,
    results_root: Path,
) -> str:
    try:
        location = directory.relative_to(results_root).as_posix()
    except ValueError:
        location = str(directory)
    repetitions_label = f"{repetitions} reps" if repetitions is not None else "unknown reps"
    return f"{category} · {experiment_id} · {repetitions_label} · {location}"


def discover_experiment_listings(results_root: str | Path) -> tuple[ExperimentListing, ...]:
    """Discover experiments using manifests only, including incompatible entries."""

    root = Path(results_root).expanduser().resolve()
    if not root.exists():
        return ()
    listings: list[ExperimentListing] = []
    for manifest_path in sorted(root.rglob("experiment_manifest.json")):
        directory = manifest_path.parent.resolve()
        try:
            manifest = _read_json(manifest_path)
            resolved = manifest.get("resolved_experiment")
            if not isinstance(resolved, dict):
                raise ValueError(f"missing resolved_experiment object in {manifest_path}")
            experiment_id = resolved.get("experiment_id")
            repetitions = resolved.get("repetitions")
            if not isinstance(experiment_id, str) or not experiment_id:
                raise ValueError(f"missing experiment_id in {manifest_path}")
            if not isinstance(repetitions, int) or repetitions < 1:
                raise ValueError(f"invalid repetitions in {manifest_path}")
            category = _lineage_category(directory, manifest)
            fingerprint = manifest.get("experiment_fingerprint")
            listings.append(ExperimentListing(
                root=directory,
                label=_listing_label(category, experiment_id, repetitions, directory, root),
                category=category,
                experiment_id=experiment_id,
                repetitions=repetitions,
                experiment_fingerprint=str(fingerprint) if fingerprint else None,
                compatible=True,
            ))
        except ValueError as exc:
            experiment_id = directory.parent.name or directory.name
            category = "INCOMPATIBLE"
            listings.append(ExperimentListing(
                root=directory,
                label=_listing_label(category, experiment_id, None, directory, root),
                category=category,
                experiment_id=experiment_id,
                repetitions=None,
                experiment_fingerprint=None,
                compatible=False,
                error=str(exc),
            ))
    priority = {
        "FINAL-VALIDATED": 0,
        "FINAL-VALIDATED (metadata warning)": 1,
        "DEVELOPMENT": 2,
        "SUPERSEDED": 3,
        "OTHER": 4,
        "INCOMPATIBLE": 5,
    }
    return tuple(sorted(
        listings,
        key=lambda item: (priority.get(item.category, 99), item.experiment_id, str(item.root)),
    ))


def preferred_experiment_index(
    listings: Iterable[ExperimentListing],
    *,
    preferred_experiment_id: str = "transaction-load-sweep",
) -> int:
    """Choose corrected final data first, with transaction load as the overview default."""

    values = tuple(listings)
    for index, item in enumerate(values):
        if (
            item.compatible
            and item.category == "FINAL-VALIDATED"
            and item.experiment_id == preferred_experiment_id
        ):
            return index
    for index, item in enumerate(values):
        if item.compatible and item.category == "FINAL-VALIDATED":
            return index
    for index, item in enumerate(values):
        if item.compatible:
            return index
    return 0


def _read_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read dashboard artifact {path}: {exc}") from exc
    if document.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError(f"unsupported artifact schema in {path}")
    return document


def _frame(rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows))
    for column in ("mean", "ci95_low", "ci95_high", "n", "mean_difference", "n_pairs"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def load_experiment(directory: str | Path) -> DashboardExperiment:
    root = Path(directory).expanduser().resolve()
    manifest = _read_json(root / "experiment_manifest.json")
    runs_document = _read_json(root / "runs.json")
    aggregate_document = _read_json(root / "aggregate.json")
    paired_document = _read_json(root / "paired_comparisons.json")
    records = runs_document.get("runs")
    if not isinstance(records, list):
        raise ValueError("runs.json must contain a runs list")
    overrides = {
        str(record["scenario_id"]): dict(record.get("scenario_overrides", {}))
        for record in records
    }
    run_rows = []
    for record in records:
        summary = record.get("summary", {})
        row = {
            "scenario_id": record.get("scenario_id"),
            "repetition": record.get("repetition"),
            "strategy_id": record.get("strategy_id"),
            "workload_fingerprint": record.get("workload_fingerprint"),
            "artifact_directory": record.get("artifact_directory"),
        }
        for key, value in summary.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                row[key] = value
        run_rows.append(row)
    sample_config = None
    if records:
        config_path = Path(records[0]["artifact_directory"]) / "config.json"
        if config_path.exists():
            sample_config = _read_json(config_path)
    return DashboardExperiment(
        root=root,
        manifest=manifest,
        runs=_frame(run_rows),
        aggregate=_frame(aggregate_document.get("rows", [])),
        paired=_frame(paired_document.get("rows", [])),
        scenario_overrides=overrides,
        sample_config=sample_config,
    )


def scenario_label(scenario_id: str, overrides: dict[str, dict[str, Any]]) -> str:
    values = overrides.get(scenario_id, {})
    if not values:
        return scenario_id
    detail = ", ".join(f"{key.split('.')[-1]}={value}" for key, value in sorted(values.items()))
    return f"{scenario_id} · {detail}"


def metric_table(
    experiment: DashboardExperiment,
    metrics: Iterable[str],
    strategies: Iterable[str] | None = None,
) -> pd.DataFrame:
    frame = experiment.aggregate
    if frame.empty or "metric" not in frame:
        return frame.copy()
    selected = frame[frame["metric"].isin(tuple(metrics))].copy()
    if strategies is not None:
        selected = selected[selected["strategy_id"].isin(tuple(strategies))]
    selected["strategy"] = selected["strategy_id"].map(STRATEGY_LABELS).fillna(
        selected["strategy_id"]
    )
    selected["scenario"] = selected["scenario_id"].map(
        lambda item: scenario_label(str(item), experiment.scenario_overrides)
    )
    return selected


def outcome_table(experiment: DashboardExperiment) -> pd.DataFrame:
    metrics = (
        "completed_total",
        "failed_transactions",
        "rejected_transactions",
        "unfinished_transactions",
    )
    frame = metric_table(experiment, metrics)
    if frame.empty:
        return frame
    return frame.pivot_table(
        index=["scenario", "strategy"], columns="metric", values="mean", aggfunc="first"
    ).reset_index()


def ratio_table(experiment: DashboardExperiment, strategies: Iterable[str]) -> pd.DataFrame:
    """Return run-level outcome ratios; zero-offer runs remain undefined."""

    required = {
        "offered_transactions",
        "completed_total",
        "rejected_transactions",
        "failed_transactions",
        "unfinished_transactions",
    }
    if experiment.runs.empty or not required <= set(experiment.runs.columns):
        return pd.DataFrame()
    frame = experiment.runs[experiment.runs["strategy_id"].isin(tuple(strategies))].copy()
    denominator = frame["offered_transactions"].replace(0, float("nan"))
    for outcome in ("completed", "rejected", "failed", "unfinished"):
        source = "completed_total" if outcome == "completed" else f"{outcome}_transactions"
        frame[f"{outcome}_ratio"] = frame[source] / denominator
    frame["strategy"] = frame["strategy_id"].map(STRATEGY_LABELS).fillna(frame["strategy_id"])
    frame["scenario"] = frame["scenario_id"].map(
        lambda item: scenario_label(str(item), experiment.scenario_overrides)
    )
    return frame


def downloadable_csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
