"""Streamlit dashboard for persisted SC6019 experiment artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from da_rollup_bench.dashboard_data import (  # noqa: E402
    STRATEGY_LABELS,
    discover_experiment_listings,
    downloadable_csv,
    load_experiment,
    metric_table,
    outcome_table,
    preferred_experiment_index,
)


COLORS = {
    "Raw calldata": "#2563EB",
    "Compressed calldata": "#7C3AED",
    "Mock external DA": "#D97706",
}
PLOT_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToAdd": ["toImage"],
    "toImageButtonOptions": {"format": "png", "filename": "sc6019-dashboard-chart", "scale": 2},
}


def metric_chart(data, metric, title, y_label, *, show_ci, x_metric="offered_rate_tps"):
    y = data[data["metric"] == metric].copy()
    x = data[data["metric"] == x_metric][["scenario_id", "strategy_id", "mean"]].rename(
        columns={"mean": "x"}
    )
    y = y.merge(x, on=["scenario_id", "strategy_id"], how="left")
    if y.empty:
        st.info(f"{title}: metric unavailable in this artifact.")
        return
    categorical = y["x"].nunique(dropna=True) <= 1 and y["scenario_id"].nunique() > 1
    x_column = "scenario" if categorical else "x"
    x_label = "Scenario" if categorical else "Offered transactions (tx/s)"
    fig = px.line(
        y, x=x_column, y="mean", color="strategy", markers=True,
        color_discrete_map=COLORS, labels={x_column: x_label, "mean": y_label},
        title=title,
    )
    if show_ci:
        for trace in fig.data:
            rows = y[y["strategy"] == trace.name]
            if not categorical:
                rows = rows.sort_values("x")
            if rows["ci95_low"].notna().any():
                trace.error_y = dict(
                    type="data", symmetric=False,
                    array=(rows["ci95_high"] - rows["mean"]).clip(lower=0),
                    arrayminus=(rows["mean"] - rows["ci95_low"]).clip(lower=0),
                )
    st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG, key=f"metric-{metric}")


st.set_page_config(page_title="SC6019 DA Benchmark", page_icon="📊", layout="wide")
st.title("SC6019 · Data Availability Benchmark")
st.caption("Read-only exploration of validated, persisted simulation artifacts")

default_root = REPOSITORY / "results"
results_root = Path(st.sidebar.text_input("Results directory", str(default_root)))
st.sidebar.button("Refresh experiments", help="Rescan manifests without using cached discovery data")
experiments = discover_experiment_listings(results_root)
if not experiments:
    st.warning("No experiment manifests were found. Run a matrix experiment, then reload this page.")
    st.stop()
selected = st.sidebar.selectbox(
    "Experiment",
    experiments,
    index=preferred_experiment_index(experiments),
    format_func=lambda item: item.label,
)
st.sidebar.caption(f"Artifact directory: `{selected.root}`")
if not selected.compatible:
    st.error(f"This artifact cannot be loaded: {selected.error}")
    st.stop()
try:
    data = load_experiment(selected.root)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

present_strategies = (
    tuple(sorted(data.aggregate["strategy_id"].dropna().unique()))
    if "strategy_id" in data.aggregate else ()
)
selected_strategies = st.sidebar.multiselect(
    "Strategies", present_strategies, default=present_strategies,
    format_func=lambda value: STRATEGY_LABELS.get(value, value),
)
show_ci = st.sidebar.toggle("Show 95% confidence intervals", value=True)
filtered = data.aggregate[data.aggregate["strategy_id"].isin(selected_strategies)].copy()
filtered["strategy"] = filtered["strategy_id"].map(STRATEGY_LABELS).fillna(filtered["strategy_id"])

overview, performance, cost, assumptions = st.tabs(
    ["Overview", "Load & Performance", "Cost & DA Overhead", "Trade-offs & Assumptions"]
)

with overview:
    resolved = data.manifest.get("resolved_experiment", {})
    cols = st.columns(4)
    cols[0].metric("Scenarios", data.runs["scenario_id"].nunique() if not data.runs.empty else 0)
    cols[1].metric("Strategies", data.runs["strategy_id"].nunique() if not data.runs.empty else 0)
    cols[2].metric("Repetitions", resolved.get("repetitions", "—"))
    cols[3].metric("Runs", len(data.runs))
    st.caption(f"Selected artifact directory: `{data.root}`")
    st.subheader("Outcome counts (mean per run)")
    outcomes = outcome_table(data)
    if outcomes.empty:
        st.info("Outcome metrics are unavailable.")
    else:
        st.dataframe(outcomes, width="stretch", hide_index=True)
        st.download_button("Download outcome CSV", downloadable_csv(outcomes), "outcomes.csv", "text/csv")
    with st.expander("Configuration and reproducibility metadata"):
        st.json({
            "experiment_fingerprint": data.manifest.get("experiment_fingerprint"),
            "runtime": data.manifest.get("runtime"),
            "resolved_experiment": resolved,
        })

with performance:
    chart_data = metric_table(data, (
        "offered_rate_tps", "completed_throughput_tps", "latency_p50_seconds",
        "latency_p95_seconds", "average_queue_depth", "resource_utilization",
    ), selected_strategies)
    left, right = st.columns(2)
    with left:
        metric_chart(chart_data, "completed_throughput_tps", "Throughput", "Completed throughput (tx/s)", show_ci=show_ci)
        metric_chart(chart_data, "average_queue_depth", "Queue depth", "Average queued publications", show_ci=show_ci)
    with right:
        metric_chart(chart_data, "latency_p50_seconds", "P50 end-to-end latency", "Latency (seconds)", show_ci=show_ci)
        metric_chart(chart_data, "latency_p95_seconds", "P95 end-to-end latency", "Latency (seconds)", show_ci=show_ci)
        metric_chart(chart_data, "resource_utilization", "Configured resource utilization", "Utilization (fraction)", show_ci=show_ci)
    ratios = metric_table(data, (
        "completion_ratio", "rejection_ratio", "failure_ratio", "unfinished_ratio"
    ), selected_strategies)
    st.subheader("Completion and terminal outcome ratios")
    if ratios.empty:
        st.info("Outcome ratios are unavailable for this artifact.")
    else:
        fig = px.bar(ratios, x="scenario", y="mean", color="metric", facet_col="strategy", barmode="stack",
                     labels={"mean": "Mean transaction ratio", "metric": "Outcome"})
        st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG, key="outcome-ratios")

with cost:
    bytes_data = metric_table(data, ("raw_serialized_bytes", "encoded_logical_bytes"), selected_strategies)
    if bytes_data.empty:
        st.info("Byte metrics are unavailable.")
    else:
        fig = px.bar(bytes_data, x="scenario", y="mean", color="metric", facet_col="strategy", barmode="group",
                     labels={"mean": "Bytes per run", "metric": "Representation"}, title="Serialized and encoded DA bytes")
        st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG, key="da-bytes")
    gas_data = metric_table(data, ("ethereum_consumed_gas",), selected_strategies)
    if not gas_data.empty:
        fig = px.bar(gas_data, x="scenario", y="mean", color="strategy", color_discrete_map=COLORS,
                     labels={"mean": "Consumed gas per run"}, title="Ethereum calldata gas usage")
        st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG, key="ethereum-gas")
        paired_columns = {"metric", "left_strategy", "right_strategy"}
        savings = pd.DataFrame()
        if paired_columns <= set(data.paired.columns):
            savings = data.paired[
                (data.paired["metric"] == "ethereum_consumed_gas")
                & (data.paired["left_strategy"] == "ethereum_calldata_raw")
                & (data.paired["right_strategy"] == "ethereum_calldata_zlib")
            ].copy()
        if not savings.empty:
            savings = savings.rename(columns={"mean_difference": "raw_minus_compressed_gas"})
            st.caption("Positive raw-minus-compressed values are modeled gas savings; negative values mean compression used more gas.")
            st.dataframe(
                savings[["scenario_id", "n_pairs", "raw_minus_compressed_gas", "ci95_low", "ci95_high"]],
                width="stretch", hide_index=True,
            )
    elif any(item.startswith("ethereum_") for item in selected_strategies):
        st.info("Ethereum gas totals were not aggregated by this artifact version; per-run costs remain available below.")
    compression = metric_table(data, ("encoded_to_raw_ratio",), selected_strategies)
    if not compression.empty:
        fig = px.bar(compression, x="scenario", y="mean", color="strategy", color_discrete_map=COLORS,
                     labels={"mean": "Encoded / serialized bytes"}, title="Encoding ratio (lower is smaller)")
        st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG, key="encoding-ratio")
    cost_metrics = sorted({metric for metric in filtered.get("metric", []) if str(metric).startswith("cost_per_completed::")})
    for metric in cost_metrics:
        unit = metric.split("::", 1)[1]
        rows = filtered[filtered["metric"] == metric]
        fig = px.line(rows, x="scenario_id", y="mean", color="strategy", markers=True,
                      color_discrete_map=COLORS,
                      labels={"scenario_id": "Scenario", "mean": f"Cost per completed transaction ({unit})"},
                      title=f"Cost per completed transaction · {unit}")
        st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG, key=f"cost-{unit}")
    st.download_button("Download filtered aggregate CSV", downloadable_csv(filtered), "aggregate-filtered.csv", "text/csv")

with assumptions:
    st.markdown("""
    **Ethereum calldata.** Raw and zlib-compressed payloads are modeled as calldata transactions using the configured EIP-aware accounting profile. The per-block DA gas budget is a simulation abstraction, not a dedicated Ethereum mainnet quota.

    **Mock external DA.** This is a generic service-capacity model with configured bandwidth, concurrency, queue capacity, fees, and independent Bernoulli availability per attempt. Retries are bounded. It is not a named network or an empirical security guarantee.

    **Interpretation.** The strategies have different trust and settlement assumptions. No universal security score or exchange rate is defined. Wei/ETH and `MOCK_DA_UNIT` must be interpreted separately.
    """)
    if data.sample_config:
        external = data.sample_config.get("external_da", {})
        st.subheader("Resolved mock-DA assumptions")
        st.json({
            "profile_name": external.get("profile_name"),
            "availability_probability": external.get("availability_probability"),
            "max_retries": external.get("max_retries"),
            "initial_backoff_seconds": external.get("initial_backoff_seconds"),
            "backoff_multiplier": external.get("backoff_multiplier"),
            "trust_assumptions": external.get("trust_assumptions"),
        })
    st.caption("Confidence intervals quantify stochastic run-to-run variation only; they do not quantify model uncertainty or external validity.")
