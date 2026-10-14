# SC6019 Data Availability-Aware Rollup Benchmarking Platform

This repository currently implements Milestones 1–10 of the approved plan:

1. strict, versioned YAML configuration;
2. deterministic synthetic workload generation with independent random streams;
3. transaction batching and canonical length-prefix serialization; and
4. Ethereum calldata gas accounting under EIP-2028 and EIP-7623-aware profiles;
5. deterministic zlib-compressed calldata accounting; and
6. generic mock external-DA publication requirements, availability, and retry policies;
7. a deterministic discrete-event engine with stateful batching and finite resources; and
8. ledger-derived metrics, conservation checks, capacity validation, and fairness checks; and
9. paired experiment orchestration, versioned artifacts, run-level statistics, safe resume, and CLI commands; and
10. a read-only Streamlit/Plotly dashboard for persisted experiment artifacts.

The defaults are illustrative rather than measurements of a live rollup. The mock external DA is not a real-network model. No blockchain node or live network integration is used.

## CLI

```powershell
$env:PYTHONPATH = (Resolve-Path 'src')
python -m da_rollup_bench.cli validate-config configs\baseline.yaml
python -m da_rollup_bench.cli run-matrix configs\experiments\transaction_load_sweep.yaml --output-root results
```

See `docs/MILESTONE9_ORCHESTRATION.md` for all commands, artifact schemas, resume behavior, and statistical methodology.

## Dashboard

Install the optional dashboard dependencies from PowerShell:

```powershell
python -m pip install -e ".[test,dashboard]"
```

Generate an experiment if needed, then launch the read-only dashboard:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src')
python -m da_rollup_bench.cli run-matrix configs\experiments\transaction_load_sweep.yaml --output-root results
python -m streamlit run dashboard\app.py
```

Open the local URL printed by Streamlit. Use the four tabs for Overview, Load & Performance, Cost & DA Overhead, and Trade-offs & Assumptions. The sidebar accepts another results directory and filters strategies. Plotly's camera button downloads an individual chart as PNG; dashboard tables expose CSV downloads.

The dashboard never runs the simulator or recomputes confidence intervals. It reads persisted `runs.json`, `aggregate.json`, and `paired_comparisons.json` artifacts. Wei and `MOCK_DA_UNIT` costs are rendered in separate charts.

## Run the tests

From PowerShell, with Python 3.11 or newer and the project test dependencies available:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src')
python -m pytest
```

See `docs/EXPERIMENT_RESULTS_REVIEW.md` for the Milestone 10 evidence review, configuration adjustments, measured trends, and interpretation limits.

Final 30-repetition results, validated artifact paths, supplementary external-DA sensitivity analysis, and scientific limitations are documented in `docs/FINAL_EXPERIMENT_ANALYSIS.md`. Only `results/final-validated` should be used for Milestone 11A analysis; earlier `results/final` artifacts predate independent per-repetition availability seeding.

The baseline input is `configs/baseline.yaml`. The EIP-7623-aware profile is the default and supports only an ordinary, non-contract-creation transaction with no access list, authorization list, initcode, or blob fields. Execution gas means EVM execution gas after refunds. See `PHASE_0_PLAN.md` for formulas, latency semantics, experiments, acceptance criteria, and deferred scope.
