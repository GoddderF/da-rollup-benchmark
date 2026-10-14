import pytest

from da_rollup_bench.statistics import estimate, numeric_metrics, paired_comparisons


def test_student_t_interval_uses_run_level_samples() -> None:
    result = estimate([1.0, 2.0, 3.0])
    assert result.n == 3
    assert result.mean == 2.0
    # mean 2, SE sqrt(1/3), t(df=2)=4.303
    margin = 4.303 / (3**0.5)
    assert result.ci95_low == pytest.approx(2 - margin)
    assert result.ci95_high == pytest.approx(2 + margin)


def test_undefined_values_are_excluded_and_report_sample_size() -> None:
    assert estimate([None, None]).n == 0
    singleton = estimate([None, 4.0])
    assert singleton.n == 1
    assert singleton.mean == 4.0
    assert singleton.ci95_low is None


def test_paired_comparisons_do_not_compare_incompatible_cost_units() -> None:
    records = [
        {
            "scenario_id": "s",
            "repetition": 0,
            "strategy_id": "raw",
            "summary": {
                "offered_rate_tps": 1,
                "completed_throughput_tps": 1,
                "drained_makespan_throughput_tps": 1,
                "completion_ratio": 1,
                "completed_total": 1,
                "failed_transactions": 0,
                "rejected_transactions": 0,
                "unfinished_transactions": 0,
                "publication_attempts": 1,
                "failed_attempts": 0,
                "retries": 0,
                "mean_batching_latency_seconds": 0,
                "mean_queue_latency_seconds": 1,
                "mean_service_latency_seconds": 0,
                "mean_retry_backoff_seconds": 0,
                "mean_confirmation_latency_seconds": 0,
                "raw_serialized_bytes": 5,
                "encoded_logical_bytes": 5,
                "attempted_encoded_bytes": 5,
                "average_queue_depth": 1,
                "maximum_queue_depth": 1,
                "resource_utilization": 0.5,
                "latency_percentiles_seconds": {"p50": 1},
                "total_attempted_cost_by_unit": {"wei": "10"},
                "cost_per_completed_transaction_by_unit": {"wei": "10"},
            },
        },
        {
            "scenario_id": "s",
            "repetition": 0,
            "strategy_id": "mock",
            "summary": {
                "offered_rate_tps": 1,
                "completed_throughput_tps": 1,
                "drained_makespan_throughput_tps": 1,
                "completion_ratio": 1,
                "completed_total": 1,
                "failed_transactions": 0,
                "rejected_transactions": 0,
                "unfinished_transactions": 0,
                "publication_attempts": 1,
                "failed_attempts": 0,
                "retries": 0,
                "mean_batching_latency_seconds": 0,
                "mean_queue_latency_seconds": 0,
                "mean_service_latency_seconds": 1,
                "mean_retry_backoff_seconds": 0,
                "mean_confirmation_latency_seconds": 0,
                "raw_serialized_bytes": 5,
                "encoded_logical_bytes": 5,
                "attempted_encoded_bytes": 5,
                "average_queue_depth": 0,
                "maximum_queue_depth": 0,
                "resource_utilization": 0.5,
                "latency_percentiles_seconds": {"p50": 1},
                "total_attempted_cost_by_unit": {"MOCK_DA_UNIT": "2"},
                "cost_per_completed_transaction_by_unit": {"MOCK_DA_UNIT": "2"},
            },
        },
    ]
    rows = paired_comparisons(records)
    assert any(row["metric"] == "completed_throughput_tps" for row in rows)
    assert not any("cost" in row["metric"] for row in rows)


def test_dashboard_metrics_include_ratios_gas_and_encoding() -> None:
    summary = {
        "rejection_ratio": 0.25,
        "failure_ratio": 0.0,
        "unfinished_ratio": 0.5,
        "encoded_to_raw_ratio": 0.75,
        "ethereum_consumed_gas": 123,
        "ethereum_available_gas_budget": 456,
    }
    metrics = numeric_metrics(summary)
    assert metrics["rejection_ratio"] == 0.25
    assert metrics["encoded_to_raw_ratio"] == 0.75
    assert metrics["ethereum_consumed_gas"] == 123
