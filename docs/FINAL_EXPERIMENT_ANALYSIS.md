# Milestone 11A: Final Experiments and Scientific Analysis

Date: 2026-10-13

## Scope and validation status

This document reports the three approved primary experiments and one separately labeled external-DA sensitivity analysis. Every scenario uses 30 independent run-level repetitions. Within a primary `(scenario, repetition)`, raw calldata, compressed calldata, and mock external DA receive the same workload fingerprint, transaction sequence, serialized batches, and logical batch membership.

During final validation, the orchestrator was found to vary the workload seed but not the external availability seed. That made Bernoulli failure sequences repeat across repetitions. The defect was corrected with a deterministic, domain-separated availability seed per repetition. Seed policy `v2-independent-workload-and-external-availability` is part of the experiment identity, and every run records its derived availability seed. All results below come only from `results/final-validated`; the earlier `results/final` artifacts are superseded and must not be cited.

Validation results:

- 1,050 accepted runs: 270 per primary experiment and 240 sensitivity runs.
- All four artifact directories passed per-file hash checks and stored simulation invariants.
- Persisted aggregate and paired tables exactly match regeneration from `runs.json`.
- All scenarios contain 30 distinct availability seeds.
- Cross-strategy workload fingerprints and batch signatures match within every paired repetition.
- No final aggregate mean is undefined; no scenario has zero completions.
- Complete test suite: `90 passed`.

Values below are run-level means with two-sided 95% Student t confidence intervals in brackets; `n = 30` throughout. Intervals measure stochastic run-to-run variation under this model, not model uncertainty or real-network uncertainty.

## Final artifact directories

- Transaction load: `results/final-validated/transaction-load-sweep/964bd69099bee43a`
- Batch size: `results/final-validated/batch-size-sweep/5fac4fb4007ba825`
- Compressibility: `results/final-validated/data-compressibility-sweep/d6d86845620b2486`
- External-DA sensitivity: `results/final-validated/external-da-sensitivity/e34fb505bacd3117`

Each directory contains `experiment_manifest.json`, `runs.json/csv`, `aggregate.json/csv`, `paired_comparisons.json/csv`, and self-validating per-run artifacts.

## 1. Transaction load sweep

The configured rates are illustrative load points for the modeled 30-million-gas/12-second Ethereum resource abstraction, not measured Ethereum mainnet capacity.

| Configured TPS | Strategy | Offered TPS | In-window throughput TPS | P95 latency (s) | Avg. queue | Utilization |
|---:|---|---:|---:|---:|---:|---:|
| 25 | Raw calldata | 24.82 [24.59, 25.04] | 19.40 [19.23, 19.58] | 12.73 [12.68, 12.78] | 2.68 [2.66, 2.70] | 0.070 [0.070, 0.071] |
| 25 | Compressed calldata | 24.82 [24.59, 25.04] | 19.40 [19.23, 19.58] | 12.73 [12.68, 12.78] | 2.68 [2.66, 2.70] | 0.071 [0.070, 0.071] |
| 25 | Mock external DA | 24.82 [24.59, 25.04] | 24.47 [24.25, 24.69] | 2.00 [1.99, 2.00] | 0.00 | 0.008 |
| 250 | Raw calldata | 249.83 [249.03, 250.63] | 199.22 [198.46, 199.98] | 11.60 [11.58, 11.62] | 12.59 [12.54, 12.65] | 0.688 [0.685, 0.690] |
| 250 | Compressed calldata | 249.83 [249.03, 250.63] | 199.22 [198.46, 199.98] | 11.60 [11.58, 11.62] | 12.59 [12.54, 12.65] | 0.690 [0.688, 0.693] |
| 250 | Mock external DA | 249.83 [249.03, 250.63] | 248.61 [247.71, 249.51] | 0.459 [0.457, 0.460] | 0.00 | 0.044 [0.044, 0.044] |
| 400 | Raw calldata | 400.11 [399.32, 400.89] | 240.00 [240.00, 240.00] | 27.03 [26.93, 27.14] | 46.15 [45.81, 46.49] | 0.944 [0.942, 0.946] |
| 400 | Compressed calldata | 400.11 [399.32, 400.89] | 240.00 [240.00, 240.00] | 27.03 [26.93, 27.14] | 46.15 [45.81, 46.49] | 0.948 [0.946, 0.950] |
| 400 | Mock external DA | 400.11 [399.32, 400.89] | 398.83 [398.08, 399.58] | 0.313 [0.312, 0.314] | 0.00 | 0.071 [0.070, 0.071] |

Ethereum throughput rises with offered load until the 400-TPS case, where it is deterministically slot-limited at 240 in-window TPS. Queue depth and P95 latency then increase sharply. Raw and compressed high-entropy batches occupy the same block schedule, so their paired throughput and latency differences are exactly zero. Compressed high-entropy calldata uses slightly more gas: raw-minus-compressed gas is -83,668 [-84,401, -82,935], -493,685 [-495,894, -491,477], and -790,991 [-793,331, -788,650] gas as load rises.

All transactions eventually complete under drain, so completion ratio is 1.0 even in overload. This does not contradict the 240-TPS primary throughput: post-horizon completions are excluded from its numerator. The mock external profile is deliberately overprovisioned in this primary sweep. Its falling batching latency at higher load reflects faster batch filling, not a general claim that more load improves real DA latency.

## 2. Batch-size sweep

| Max tx/batch | Mean batching delay (s) | Raw gas/run | Raw cost/completed (wei) | Mock P95 latency (s) | Mock attempted cost (MOCK_DA_UNIT) |
|---:|---:|---:|---:|---:|---:|
| 5 | 0.203 [0.198, 0.207] | 7.27M [7.14M, 7.39M] | 12.27T [12.26T, 12.27T] | 0.646 [0.632, 0.660] | 0.240 [0.236, 0.244] |
| 20 | 0.891 [0.878, 0.903] | 5.51M [5.43M, 5.59M] | 9.19T [9.18T, 9.20T] | 1.924 [1.906, 1.942] | 0.155 [0.153, 0.157] |
| 100 | 1.045 [1.038, 1.053] | 5.44M [5.37M, 5.51M] | 9.06T [9.04T, 9.07T] | 2.043 [2.041, 2.045] | 0.152 [0.150, 0.154] |

Small batches reduce batching delay but create more publications and fixed transaction overhead. Moving from 5 to 20 transactions produces the largest efficiency gain; moving from 20 to 100 yields a smaller improvement because the 2-second timer usually closes the baseline workload before 100 transactions accumulate. For high-entropy payloads, zlib adds 1.08%, 0.29%, and 0.22% encoded-byte overhead at the three batch limits and raises gas/cost slightly. Ethereum P95 latency remains dominated by block-slot waiting, while mock-DA P95 more visibly follows batching delay.

## 3. Data-compressibility sweep

| Payload model | Zlib encoded/raw ratio | Raw gas/run | Compressed gas/run | Paired raw-minus-compressed gas |
|---|---:|---:|---:|---:|
| High entropy | 1.0022 [1.0021, 1.0023] | 5.46M [5.40M, 5.53M] | 5.49M [5.42M, 5.55M] | -27,525 [-28,966, -26,083] |
| 80% zero fraction | 0.4070 [0.4064, 0.4076] | 2.57M [2.53M, 2.60M] | 2.59M [2.56M, 2.63M] | -24,588 [-26,401, -22,776] |
| Repeated | 0.0145 [0.0144, 0.0146] | 5.39M [5.33M, 5.46M] | 0.677M [0.675M, 0.680M] | 4.72M [4.65M, 4.78M] |

Byte compression and calldata gas do not have a one-to-one relationship. Under EIP-aware calldata accounting, zero bytes are cheaper than non-zero bytes. The zero-heavy raw payload already receives that discount; zlib makes a shorter but predominantly non-zero byte stream, so it saves bytes yet slightly increases total gas. Repeated non-zero payloads have no such raw zero-byte advantage and compress extremely well, producing an approximately 87% gas reduction. High-entropy input slightly expands and predictably costs more when compressed.

The paired gas intervals are intervals for run-level paired differences, not conclusions inferred from overlap between separate strategy intervals. No formal hypothesis test is claimed.

## 4. Supplementary external-DA sensitivity analysis

This separate 2×2×2 factorial holds offered load at 250 TPS and varies bandwidth (20 kB/s or 1 MB/s), service concurrency (1 or 4), and independent per-attempt availability (0.8 stress case or 0.999 illustrative base). A typical 100-transaction batch is about 20.4 kB and demand is about 2.5 publications/s. At 20 kB/s, one slot serves only about 0.93 attempts/s before retries and is overloaded; four slots provide about 3.74 attempts/s before retries and approach capacity under the 0.8 case.

| Availability | Bandwidth | Slots | In-window TPS | P95 latency (s) | Avg. queue | Utilization | Failed attempts | Failure ratio | Attempted cost (MOCK_DA_UNIT) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.8 | 20 kB/s | 1 | 73.94 [71.77, 76.12] | 147.52 [145.43, 149.60] | 52.43 [51.66, 53.21] | 0.998 | 36.63 [34.69, 38.58] | 0.0087 [0.0065, 0.0109] | 3.963 [3.921, 4.004] |
| 0.8 | 20 kB/s | 4 | 241.33 [240.04, 242.62] | 3.05 [2.88, 3.22] | 0.218 [0.148, 0.288] | 0.812 [0.800, 0.824] | 38.10 [35.30, 40.90] | 0.0091 [0.0060, 0.0123] | 3.999 [3.937, 4.060] |
| 0.8 | 1 MB/s | 1 | 246.06 [244.88, 247.23] | 0.586 [0.575, 0.597] | 0.003 | 0.219 [0.216, 0.221] | 37.93 [35.42, 40.45] | 0.0095 [0.0057, 0.0134] | 3.983 [3.935, 4.030] |
| 0.8 | 1 MB/s | 4 | 246.89 [245.98, 247.79] | 0.573 [0.562, 0.585] | 0.000 | 0.054 [0.053, 0.055] | 35.60 [32.75, 38.45] | 0.0076 [0.0051, 0.0101] | 3.945 [3.887, 4.002] |
| 0.999 | 20 kB/s | 1 | 91.50 [91.31, 91.69] | 96.49 [95.99, 96.99] | 46.79 [46.54, 47.04] | 0.998 | 0.20 [0.05, 0.35] | 0.0000 | 3.214 [3.203, 3.225] |
| 0.999 | 20 kB/s | 4 | 244.67 [243.91, 245.42] | 1.459 [1.457, 1.460] | 0.000 | 0.659 [0.657, 0.661] | 0.13 [-0.03, 0.30] | 0.0000 | 3.213 [3.203, 3.224] |
| 0.999 | 1 MB/s | 1 | 249.33 [248.37, 250.29] | 0.458 [0.457, 0.460] | 0.000 | 0.177 [0.176, 0.178] | 0.13 [-0.03, 0.30] | 0.0000 | 3.219 [3.205, 3.234] |
| 0.999 | 1 MB/s | 4 | 248.50 [247.76, 249.24] | 0.460 [0.458, 0.461] | 0.000 | 0.044 [0.044, 0.044] | 0.40 [0.19, 0.61] | 0.0000 | 3.214 [3.203, 3.225] |

The overloaded 20-kB/s single-slot resource demonstrates the capacity effect: primary throughput is far below offered load and drain-mode P95 latency extends beyond the 60-second measurement window. Four slots largely remove that bottleneck. At availability 0.8, bounded retries add service and backoff time, raise attempted cost by roughly 23% relative to the 0.999 cases, and still leave an approximately 0.8–1.0% logical publication/transaction failure ratio after three attempts. Failed attempts consume cost even when a later attempt succeeds.

The 0.999 scenarios show small nonzero mean failed-attempt counts but no exhausted logical publications in these samples. Negative lower CI bounds for rare nonnegative counts are an artifact of the symmetric Student t interval and must be interpreted as compatible with zero, not as physically negative events. Factor-level scenarios use independent workload samples rather than matched workloads, so comparisons across bandwidth/concurrency/availability are descriptive factorial contrasts, not paired hypothesis tests.

## 5. Statistical interpretation

- The independent unit is one complete simulation run; transactions within a run are not treated as repetitions.
- Primary strategy comparisons are paired within `(scenario, repetition)` because workload and batches match exactly.
- Reported intervals use `mean ± t(0.975, 29) × sample SD / sqrt(30)`.
- Non-overlap or overlap of two marginal CIs is not used as a formal significance test. Where useful, the stored paired-difference interval is reported directly.
- No final scenario has zero completions or undefined cost-per-completion. If zero completions occurred, that metric would be reported as undefined rather than zero.
- Deterministic zero-width intervals, such as Ethereum overload throughput at 240 TPS, indicate identical outcomes under the model, not certainty about real systems.
- Statistical intervals do not cover parameter choice, workload realism, implementation/model error, correlated outages, adversarial behavior, or external validity.

## 6. Trust and security interpretation

**Ethereum raw calldata** places the serialized batch data directly in Ethereum calldata under the modeled transaction profile. The simulation treats Ethereum inclusion/confirmation as the publication path and charges wei. Its security interpretation inherits the assumed Ethereum settlement/data-publication model, but the configured DA gas budget is only a simulation abstraction.

**Ethereum compressed calldata** uses the same publication and trust path after deterministic zlib encoding. Compression changes bytes and gas, not the underlying publication trust assumption. Decompression correctness is locally validated; the model does not include decompressor implementation vulnerabilities or on-chain decompression execution.

**Generic mock external DA** uses a separate operator/service assumption, `MOCK_DA_UNIT`, bandwidth/concurrency capacity, and independent Bernoulli availability with bounded retry. It does not model a specific network, data-availability sampling, erasure coding, slashing, correlated outages, censorship, adversarial withholding, or settlement enforcement. Better modeled latency or throughput is not evidence of equivalent security to Ethereum.

No universal security score is defined. Wei and `MOCK_DA_UNIT` are not converted or compared economically.

## 7. Supported findings versus illustrative assumptions

Supported by this deterministic simulator and the stated configurations:

- Ethereum slot capacity produces throughput saturation, queue growth, and higher latency under overload.
- Small batches trade lower batching delay for greater fixed publication overhead.
- Compressibility can materially reduce bytes, but calldata gas depends on byte values as well as byte count.
- Limited external service capacity creates queues; concurrency and bandwidth relieve them.
- Failed attempts add service, backoff, and attempted cost, and bounded retries can still exhaust.

Illustrative rather than empirically established:

- All absolute capacity, latency, fee, and availability values.
- The 30-million-gas per-slot abstraction as a dedicated DA budget.
- Independent Bernoulli availability and the selected 0.8/0.999 probabilities.
- The generic external operator/trust model and mock fees.
- Applicability of synthetic fixed-size Poisson workloads to a production rollup.

## 8. Reproducible commands

From PowerShell in the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src')

python -m da_rollup_bench.cli run-matrix configs\experiments\transaction_load_sweep.yaml --output-root results\final-validated --preset final
python -m da_rollup_bench.cli run-matrix configs\experiments\batch_size_sweep.yaml --output-root results\final-validated --preset final
python -m da_rollup_bench.cli run-matrix configs\experiments\data_compressibility_sweep.yaml --output-root results\final-validated --preset final
python -m da_rollup_bench.cli run-matrix configs\experiments\external_da_sensitivity.yaml --output-root results\final-validated

Get-ChildItem results\final-validated -Directory | ForEach-Object {
    $artifact = Get-ChildItem $_.FullName -Directory | Select-Object -First 1
    python -m da_rollup_bench.cli validate-artifacts $artifact.FullName
}

python -m pytest -q
python -m streamlit run dashboard\app.py
```

Safe reruns resume only when immutable experiment identity and every existing artifact hash match. Runtime metadata is recorded for provenance but is not treated as experiment identity because Git revision lookup can be unavailable after moving an otherwise identical checkout.

## 9. Suggested final-report figures

1. Offered TPS versus primary completed throughput, with 95% CIs and the Ethereum saturation plateau.
2. Offered TPS versus P95 latency and average publication queue depth.
3. Batch limit versus mean batching latency and raw Ethereum cost per completed transaction.
4. Encoded/raw byte ratio by payload model.
5. Raw versus compressed Ethereum gas by payload model, plus paired gas-difference intervals.
6. External sensitivity heatmaps for P95 latency and in-window throughput, faceted by availability.
7. External availability versus failed attempts, failure ratio, retry backoff, and total attempted `MOCK_DA_UNIT` cost.

Figures must keep wei and `MOCK_DA_UNIT` on separate axes/panels and label the sensitivity study as supplementary.

## 10. Key limitations

- Synthetic workload, fixed payload size, and illustrative model parameters.
- EIP-aware calldata only; no EIP-4844 blob publication.
- No empirical compression CPU time in simulated latency.
- Independent availability failures; no correlated or adversarial failures.
- Drain completion can conceal overload if completion ratio is viewed without in-window throughput and latency.
- Symmetric t intervals can extend below zero for rare count metrics.
- No economic conversion between monetary units and no security equivalence claim.
- Results establish behavior of this model, not production performance or security guarantees.
