# Milestone 9: Experiment Orchestration and Reproducibility

Date: 2026-10-12

## Pre-implementation validation

The engine and metrics implementation were inspected and exercised using `tests/fixtures/cross_strategy_small.json`. The fixture fixes transaction IDs, arrival timestamps, payload bytes, batching configuration, and expected batch membership independently of the workload generator.

All three strategies receive the same `Transaction` tuple and produce the same workload fingerprint and logical batches. Strategy preparation changes only encoded payloads, resource requirements, and explicit monetary units. Raw and compressed calldata use wei; mock external DA uses `MOCK_DA_UNIT`.

Existing deterministic tests additionally verify truncate/drain denominators, retry latency and failed-attempt fees, queue saturation, overload, transaction/batch conservation, and capacity invariants. No new engine correctness defect was found. The missing persisted cross-strategy fixture was added as a validation improvement.

## Orchestration model

An experiment YAML references one strict base project configuration and defines a Cartesian matrix of dotted configuration paths. Paths are validated against the project schema. Each resolved scenario receives a deterministic ID derived from its sorted overrides.

For every `(scenario, repetition)`:

1. derive one deterministic seed from the base seed, experiment ID, scenario ID, and repetition;
2. generate the workload exactly once;
3. persist its fingerprint and canonical workload artifact;
4. replay that same in-memory workload through raw calldata, compressed calldata, and mock external DA;
5. validate simulation invariants and cross-strategy batch signatures; and
6. persist per-run artifacts only after validation passes.

Development and final presets use 10 and 30 repetitions respectively unless an experiment explicitly sets `repetitions`. The CLI `--preset` option deliberately overrides the file for a new fingerprinted output directory.

## Deterministic artifacts and resume

Output directory:

```text
<output-root>/<experiment-id>/<experiment-fingerprint-prefix>/
```

The experiment fingerprint covers the resolved base configuration, matrix, strategies, and effective repetition count. Each run identity additionally contains scenario, repetition, derived seed, strategy, configuration fingerprint, and workload fingerprint.

Writes use a temporary sibling followed by atomic replacement. A run is resumed only when its manifest identity matches and every recorded artifact hash validates. Nonempty directories without manifests, modified artifacts, and incompatible identities are rejected rather than overwritten.

Per-run artifacts:

- `manifest.json`
- `config.json`
- `workload.json`
- `result.json`
- `summary.json`
- `validation.json`
- `transactions.csv`
- `publications.csv`

Experiment artifacts:

- `experiment_manifest.json`
- `runs.json` and `runs.csv`
- `aggregate.json` and `aggregate.csv`
- `paired_comparisons.json` and `paired_comparisons.csv`

All JSON artifacts carry schema version 1. Manifests record Python, implementation, platform, zlib runtime, and Git revision when available.

## Statistical methodology

Descriptive summaries are computed per complete simulation run. Across-repetition means and confidence intervals use run-level values only; transactions within a run are never treated as independent repetitions.

The interval is a two-sided 95% Student t interval:

```text
mean +/- t(0.975, n-1) * sample_standard_deviation / sqrt(n)
```

Outputs include `n`, interval bounds, and the method string. For `n=1`, the mean is reported and interval bounds are undefined. With zero defined observations, mean and bounds are undefined. Cost per completed transaction is undefined when no transaction completes.

Paired comparisons subtract strategy metrics within the same scenario and repetition before estimating the mean difference. Cost keys include their unit, so raw/compressed wei costs can be paired while wei and `MOCK_DA_UNIT` never intersect and are never compared.

## Primary experiment configurations

- `configs/experiments/transaction_load_sweep.yaml`
- `configs/experiments/batch_size_sweep.yaml`
- `configs/experiments/data_compressibility_sweep.yaml`

All parameters are illustrative. No calibration is performed to force an outcome. The compressibility sweep uses a fixed 0.8 zero probability only for the `zero_fraction` content model; other generators ignore it.

`configs/experiments/milestone9_validation.yaml` is a small two-repetition underload/overload checkpoint and not a research-quality experiment.

## PowerShell commands

From the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src')
python -m da_rollup_bench.cli validate-config configs\baseline.yaml
python -m da_rollup_bench.cli validate-config configs\experiments\transaction_load_sweep.yaml --kind experiment
python -m da_rollup_bench.cli generate-workload configs\baseline.yaml --output results\workload.json
python -m da_rollup_bench.cli run-single configs\baseline.yaml --strategy raw --output-dir results\single-raw
python -m da_rollup_bench.cli run-matrix configs\experiments\transaction_load_sweep.yaml --output-root results
python -m da_rollup_bench.cli run-matrix configs\experiments\transaction_load_sweep.yaml --output-root results --preset final
python -m da_rollup_bench.cli summarize <experiment-output-directory>
python -m da_rollup_bench.cli validate-artifacts <run-or-experiment-directory>
```

## Remaining limitations

- Statistical intervals describe simulator repetition variability, not model error or external validity.
- The t critical table uses exact tabulated values through 30 degrees of freedom and 1.96 thereafter.
- Scenario matrices are Cartesian products; coupled/non-Cartesian scenario rows are not yet supported.
- A run stores its workload in each strategy artifact as well as the shared repetition directory, favoring self-contained validation over storage efficiency.
- Result artifacts can be large because event transitions and payload bytes are preserved.
- No parallel execution, dashboard, chart generation, or empirical trace ingestion is implemented.

