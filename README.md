# Data Availability-Aware Rollup Benchmarking Platform

A reproducible, discrete-event simulator for comparing how different data-availability (DA) publication strategies affect rollup cost, throughput, and latency.

The project compares three strategies:

- **Ethereum raw calldata** — publishes the serialized batch without compression.
- **Ethereum zlib calldata** — compresses the batch with zlib before calldata publication.
- **Mock external DA** — models a configurable external service with bandwidth, concurrency, queue capacity, availability failures, retries, and a separate cost unit.

The repository does **not** include generated experiment results. Results are created locally under `results/`, which is intentionally excluded from Git. Follow the quick start below to generate them before opening the dashboard.

## What the simulator models

The pipeline is:

```text
synthetic transactions
        -> transaction batching
        -> DA encoding/publication strategy
        -> Ethereum block queue or mock external-DA queue
        -> completion ledger
        -> cost, throughput, latency, and utilization metrics
```

The simulator provides:

- deterministic synthetic workloads with independent seeded random streams;
- fixed-rate or Poisson transaction arrivals;
- fixed or categorical transaction sizes;
- high-entropy, zero-heavy, and repeated payload models;
- count-, byte-, and timer-based batching;
- EIP-2028 and EIP-7623-aware calldata gas accounting;
- deterministic zlib compression and round-trip validation;
- a finite-capacity mock external DA service with retries;
- repeatable matrix experiments and run-level 95% confidence intervals;
- versioned JSON/CSV artifacts with validation and safe resume;
- a read-only Streamlit/Plotly dashboard.

This is a benchmarking simulator, not a production rollup. It does not execute EVM transactions, generate fraud/ZK proofs, submit transactions to a live blockchain, or connect to a real DA network.

## Requirements

- Python **3.11 or newer**
- Git
- A terminal (PowerShell on Windows, or a POSIX shell on macOS/Linux)

No Ethereum node, wallet, RPC endpoint, API key, or external database is required.

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/GoddderF/da-rollup-benchmark.git
cd da-rollup-benchmark
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the project and all development/dashboard dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[test,dashboard]"
```

The editable installation makes the `da_rollup_bench` package available directly from `src/`; no manual `PYTHONPATH` setting is needed.

### 4. Validate the configuration

```bash
python -m da_rollup_bench.cli validate-config configs/baseline.yaml
python -m da_rollup_bench.cli validate-config configs/experiments/transaction_load_sweep.yaml --kind experiment
```

Both commands should print JSON containing `"valid": true`.

### 5. Generate experiment results

Run the transaction-load experiment:

```bash
python -m da_rollup_bench.cli run-matrix configs/experiments/transaction_load_sweep.yaml --output-root results
```

The default development preset runs 10 repetitions for each scenario. Results are written below:

```text
results/
  transaction-load-sweep/
    <experiment-fingerprint>/
      experiment_manifest.json
      runs.json
      aggregate.json
      paired_comparisons.json
      ...
```

Existing valid runs are safely resumed, so rerunning the same command does not repeat completed work.

### 6. Launch the dashboard

```bash
python -m streamlit run dashboard/app.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`. The dashboard discovers experiments under `results/` and never reruns or modifies the simulation.

## Available experiments

All experiment definitions are in `configs/experiments/`.

| Experiment | Purpose |
|---|---|
| `transaction_load_sweep.yaml` | Compare throughput, latency, queueing, and cost as offered TPS increases. |
| `batch_size_sweep.yaml` | Study the latency-versus-publication-overhead trade-off of different batch limits. |
| `data_compressibility_sweep.yaml` | Compare high-entropy, zero-heavy, and repeated payloads under raw and compressed publication. |
| `external_da_sensitivity.yaml` | Stress the mock external DA model across bandwidth, concurrency, and availability assumptions. |
| `milestone9_validation.yaml` | Small regression/validation experiment with deliberately constrained resources. |

Run any experiment by replacing the configuration path:

```bash
python -m da_rollup_bench.cli run-matrix configs/experiments/batch_size_sweep.yaml --output-root results
python -m da_rollup_bench.cli run-matrix configs/experiments/data_compressibility_sweep.yaml --output-root results
python -m da_rollup_bench.cli run-matrix configs/experiments/external_da_sensitivity.yaml --output-root results
```

For report-quality runs, use 30 repetitions:

```bash
python -m da_rollup_bench.cli run-matrix configs/experiments/transaction_load_sweep.yaml --output-root results/final-validated --preset final
```

Final-preset runs take longer and create more artifacts than the default development runs.

## Command-line reference

### Generate one workload

```bash
python -m da_rollup_bench.cli generate-workload configs/baseline.yaml --output results/workload.json
```

### Run one strategy

Valid strategy names are `raw`, `compressed`, and `mock_external`.

```bash
python -m da_rollup_bench.cli run-single configs/baseline.yaml --strategy raw --output-dir results/single-raw
```

### Rebuild aggregate summaries

Use the experiment directory printed by `run-matrix`:

```bash
python -m da_rollup_bench.cli summarize results/transaction-load-sweep/EXPERIMENT_FINGERPRINT
```

### Validate generated artifacts

```bash
python -m da_rollup_bench.cli validate-artifacts results/transaction-load-sweep/EXPERIMENT_FINGERPRINT
```

`EXPERIMENT_FINGERPRINT` is a placeholder. Replace it with the actual directory name generated on your machine.

## Run the tests

```bash
python -m pytest
```

The tests cover workload generation, batching, calldata accounting, compression, external-DA behavior, event scheduling, metrics, statistics, experiment orchestration, artifact validation, and dashboard data loading.

## Configuration

The baseline configuration is `configs/baseline.yaml`. Important defaults include:

- 60-second Poisson workload;
- 200-byte transactions;
- up to 100 transactions or 128,000 serialized bytes per batch;
- 2-second maximum batching wait;
- EIP-7623-aware calldata accounting;
- 12-second Ethereum block interval;
- 30,000,000-gas simulated per-block DA budget;
- zlib compression level 6;
- mock external DA with 1 MB/s bandwidth, four service slots, 0.999 independent per-attempt availability, and two retries;
- drain termination, meaning queued work may finish after the 60-second measurement horizon.

These values are illustrative model parameters, not measurements of Ethereum mainnet or a named external DA network.

## How metrics are interpreted

- **Primary throughput** is the number of transactions completed inside the measurement window divided by the window duration.
- **End-to-end latency** is completion time minus transaction arrival time. It includes batching, queueing, service, retry backoff, and configured confirmation delay.
- **Ethereum cost** is calldata gas multiplied by the configured effective gas price.
- **Mock external-DA cost** is a configured fixed fee plus a per-byte fee for every attempt, including failed attempts.
- **Cost per completed transaction** divides total attempted publication cost by completed transactions.
- **Resource utilization** is Ethereum gas consumed over simulated available gas, or external busy-server time over configured service capacity.

Ethereum costs use `wei`; mock external-DA costs use `MOCK_DA_UNIT`. They intentionally appear in separate dashboard charts and must not be compared as if they were the same currency or security model.

## Reproducibility

For each experiment repetition, the project derives deterministic seeds for workload generation and external-DA availability. All strategies in the same scenario/repetition receive the same transactions and batch membership. Aggregates and paired comparisons are computed from complete run-level repetitions rather than treating individual transactions as independent samples.

Generated artifacts include configuration and workload fingerprints, manifests, runtime metadata, validation reports, per-transaction records, per-publication records, aggregate statistics, and paired comparisons.

## Project structure

```text
configs/                 Baseline and experiment YAML files
dashboard/app.py         Streamlit dashboard
docs/                    Design and experiment-analysis documents
src/da_rollup_bench/     Simulator, strategies, metrics, and CLI
tests/                   Automated test suite
PHASE_0_PLAN.md          Detailed design, formulas, and acceptance criteria
pyproject.toml           Package metadata and dependencies
```

Generated `results/`, virtual environments, caches, and build outputs are intentionally ignored by Git.

## Troubleshooting

### Dashboard says no experiment manifests were found

Run at least one `run-matrix` command first and keep its `--output-root` as `results`, or enter the alternative results directory in the dashboard sidebar.

### `No module named da_rollup_bench`

Activate the virtual environment and rerun:

```bash
python -m pip install -e ".[test,dashboard]"
```

### `No module named yaml`, `pydantic`, `streamlit`, or `plotly`

The dependencies were not installed in the currently active Python environment. Activate `.venv` and repeat the installation command above.

### PowerShell blocks `Activate.ps1`

You can run commands using the virtual environment's Python without activating it:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test,dashboard]"
.\.venv\Scripts\python.exe -m da_rollup_bench.cli run-matrix configs/experiments/transaction_load_sweep.yaml --output-root results
.\.venv\Scripts\python.exe -m streamlit run dashboard/app.py
```

## Documentation

- `PHASE_0_PLAN.md` — architecture, formulas, latency semantics, and acceptance criteria.
- `docs/MILESTONE9_ORCHESTRATION.md` — experiment orchestration and artifact schemas.
- `docs/EXPERIMENT_RESULTS_REVIEW.md` — dashboard and experiment evidence review.
- `docs/FINAL_EXPERIMENT_ANALYSIS.md` — final findings, statistical interpretation, and limitations.

## Limitations

- Synthetic workloads rather than production rollup traces.
- No live Ethereum or external-DA integration.
- No EIP-4844 blob publication model.
- Compression CPU time is not included in simulated latency.
- External availability failures are independent Bernoulli trials; correlated and adversarial failures are not modeled.
- No economic conversion between `wei` and `MOCK_DA_UNIT`.
- Confidence intervals describe simulated run-to-run variation, not uncertainty about real networks or model validity.

The results demonstrate the behavior of the configured model. They should not be presented as production performance or security guarantees for Ethereum, Celestia, EigenDA, or any other real system.
