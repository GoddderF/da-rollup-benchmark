"""Run-level statistical summaries and paired comparisons."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable


CI_METHOD = "two-sided 95% Student t interval over independent run-level repetitions"

# Two-sided 95% t critical values for df 1..30; normal approximation thereafter.
_T_975 = (
    12.706,
    4.303,
    3.182,
    2.776,
    2.571,
    2.447,
    2.365,
    2.306,
    2.262,
    2.228,
    2.201,
    2.179,
    2.160,
    2.145,
    2.131,
    2.120,
    2.110,
    2.101,
    2.093,
    2.086,
    2.080,
    2.074,
    2.069,
    2.064,
    2.060,
    2.056,
    2.052,
    2.048,
    2.045,
    2.042,
)


@dataclass(frozen=True, slots=True)
class Estimate:
    n: int
    mean: float | None
    ci95_low: float | None
    ci95_high: float | None
    method: str


def estimate(values: Iterable[float | int | None]) -> Estimate:
    defined = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not defined:
        return Estimate(0, None, None, None, CI_METHOD)
    mean = statistics.fmean(defined)
    if len(defined) == 1:
        return Estimate(1, mean, None, None, CI_METHOD)
    standard_error = statistics.stdev(defined) / math.sqrt(len(defined))
    degrees = len(defined) - 1
    critical = _T_975[degrees - 1] if degrees <= len(_T_975) else 1.96
    margin = critical * standard_error
    return Estimate(len(defined), mean, mean - margin, mean + margin, CI_METHOD)


def numeric_metrics(summary: dict[str, Any]) -> dict[str, float | None]:
    names = (
        "offered_rate_tps",
        "completed_throughput_tps",
        "drained_makespan_throughput_tps",
        "completion_ratio",
        "completed_total",
        "failed_transactions",
        "rejected_transactions",
        "unfinished_transactions",
        "publication_attempts",
        "failed_attempts",
        "retries",
        "mean_batching_latency_seconds",
        "mean_queue_latency_seconds",
        "mean_service_latency_seconds",
        "mean_retry_backoff_seconds",
        "mean_confirmation_latency_seconds",
        "raw_serialized_bytes",
        "encoded_logical_bytes",
        "attempted_encoded_bytes",
        "average_queue_depth",
        "maximum_queue_depth",
        "resource_utilization",
    )
    metrics: dict[str, float | None] = {
        name: float(summary[name]) if summary.get(name) is not None else None for name in names
    }
    for percentile, value in summary.get("latency_percentiles_seconds", {}).items():
        metrics[f"latency_{percentile}_seconds"] = float(value)
    for unit, value in summary.get("total_attempted_cost_by_unit", {}).items():
        metrics[f"total_attempted_cost::{unit}"] = float(value)
    for unit, value in summary.get("cost_per_completed_transaction_by_unit", {}).items():
        metrics[f"cost_per_completed::{unit}"] = None if value is None else float(value)
    return metrics


def aggregate_run_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[float | None]] = defaultdict(list)
    for record in records:
        for metric, value in numeric_metrics(record["summary"]).items():
            groups[(record["scenario_id"], record["strategy_id"], metric)].append(value)
    rows = []
    for (scenario_id, strategy_id, metric), values in sorted(groups.items()):
        result = estimate(values)
        rows.append(
            {
                "scenario_id": scenario_id,
                "strategy_id": strategy_id,
                "metric": metric,
                "n": result.n,
                "mean": result.mean,
                "ci95_low": result.ci95_low,
                "ci95_high": result.ci95_high,
                "ci_method": result.method,
            }
        )
    return rows


def paired_comparisons(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_run = {
        (record["scenario_id"], record["repetition"], record["strategy_id"]): numeric_metrics(
            record["summary"]
        )
        for record in records
    }
    scenarios = sorted({key[0] for key in by_run})
    strategies = sorted({key[2] for key in by_run})
    rows = []
    for scenario in scenarios:
        repetitions = sorted({key[1] for key in by_run if key[0] == scenario})
        for left_index, left in enumerate(strategies):
            for right in strategies[left_index + 1 :]:
                paired_values: dict[str, list[float | None]] = defaultdict(list)
                for repetition in repetitions:
                    left_metrics = by_run.get((scenario, repetition, left))
                    right_metrics = by_run.get((scenario, repetition, right))
                    if left_metrics is None or right_metrics is None:
                        continue
                    for metric in sorted(set(left_metrics) & set(right_metrics)):
                        left_value = left_metrics[metric]
                        right_value = right_metrics[metric]
                        paired_values[metric].append(
                            None
                            if left_value is None or right_value is None
                            else left_value - right_value
                        )
                for metric, differences in sorted(paired_values.items()):
                    result = estimate(differences)
                    rows.append(
                        {
                            "scenario_id": scenario,
                            "left_strategy": left,
                            "right_strategy": right,
                            "metric": metric,
                            "difference": "left-minus-right",
                            "n_pairs": result.n,
                            "mean_difference": result.mean,
                            "ci95_low": result.ci95_low,
                            "ci95_high": result.ci95_high,
                            "ci_method": result.method,
                        }
                    )
    return rows
