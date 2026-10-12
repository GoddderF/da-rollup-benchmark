# Phase 0 Plan: Data Availability-Aware Rollup Benchmarking Platform

Status: approved with refinements on 2026-10-12. Project identifier: SC6019. The existing workspace directory name is intentionally unchanged.

## 1. Source of truth and interpretation

The course Option 3 brief is the primary requirements source. The project request narrows it into a reproducible three-strategy simulator. Where the request adds rigor without contradicting the brief, the stricter requirement is adopted.

| Course requirement | Phase 0 interpretation | Planned acceptance evidence |
|---|---|---|
| Build a simple rollup simulator or prototype under different DA assumptions | Build a deterministic discrete-event simulator. It models transaction arrival, batch formation, publication queues, service, and confirmation. It is not a blockchain implementation. | A run can be reproduced from a versioned config and seed. |
| Compare at least two approaches | Compare three on the exact same workload: uncompressed Ethereum calldata, zlib-compressed Ethereum calldata, and a configurable mock external DA service. | Paired results contain a workload fingerprint and identical transaction IDs. |
| Measure cost, throughput, and latency under different loads | Sweep offered transaction rate across underload, near-capacity, and overload regimes. Report completed throughput separately from offered load and explicitly decompose latency. | Machine-readable raw records plus summaries and plots. |
| Show DA overhead as transaction volume increases | Define overhead in bytes, gas/fees, compression metadata, and time; plot each against offered load and batch characteristics. | Interactive dashboard and exportable CSV/JSON in a later phase. |
| Analyze cost savings versus trust/security assumptions | Maintain a qualitative assumption matrix beside quantitative performance results. No security score or claim of superiority is inferred from cost or speed. | Report section and dashboard annotations. |
| Focus on publication cost, not only execution | Execution/proving is outside the core cost comparison. Any fixed batch posting transaction overhead is explicit; DA publication is the measured subsystem. | Cost-accounting invariant and documented exclusions. |
| Rigorous simulation is acceptable | Prefer a validated simulator to live Celestia, EigenDA, Ethereum, Solidity, nodes, paid APIs, or unverifiable scraped fee claims. | Unit, property/invariant, integration, and reproducibility tests. |
| Relate findings to calldata/blobs and external DA systems | Use calldata as the Ethereum baseline; discuss blobs and named DA systems only as contextual references unless a later approved extension models them. Mock DA is never labeled as Celestia or EigenDA data. | Terminology review and limitations section. |
| Discuss whether DA is the bottleneck | Compare arrival demand, batcher constraints, publication capacity, utilization, queue growth, and time spent in each latency component. Conclusions are scenario-specific. | Bottleneck attribution from state and queue metrics. |

## 2. MVP scope

### Included

- Python 3.11+ package with deterministic, single-threaded discrete-event execution.
- Synthetic transaction generator with configurable duration, warm-up, arrival process, arrival rate, size distribution, byte-content model, and seed.
- One common workload trace replayed by every strategy.
- Batcher with maximum transaction count, maximum uncompressed bytes, and maximum waiting time; it closes on the first limit reached.
- Three strategies:
  1. Ethereum calldata with the raw serialized batch payload.
  2. Ethereum calldata with deterministic zlib compression of that same payload.
  3. A generic external DA queue with configurable fixed/per-byte fee, bandwidth, base latency, jitter, capacity, availability/failure probability, retry policy, and declared trust assumptions.
- Configurable Ethereum protocol profile, gas price, per-publication fixed overhead, and optional execution gas.
- Raw event/batch/transaction outputs, aggregated metrics, config snapshot, seed, software version, and workload hash.
- CLI experiment runner, YAML configuration, CSV/JSON outputs, tests, and later a Streamlit/Plotly dashboard.
- Clearly labeled illustrative workload defaults; they are not empirical workload claims.
- Generic low/base/high mock external DA profiles; none represents or is named after a real network.
- Independent Bernoulli availability failures with bounded retries for the MVP.
- Development experiments use 10 repetitions; final stochastic experiments target 30, subject to runtime and interval stability.

### Explicitly deferred

- Live Ethereum, Celestia, EigenDA, or other RPC integration; observed mainnet fee feeds.
- Solidity contracts, rollup node software, proof generation, execution benchmarking, sequencer consensus, L1 reorgs, bridging, withdrawals, and full finality economics.
- EIP-4844 blob publication as a measured fourth strategy. It may be added only with a separate blob fee/capacity model; it must never reuse calldata accounting.
- Real data-availability sampling, erasure coding, validator/operator topology, slashing, adversarial correlated failures, censorship, and cryptographic verification.
- A universal numeric “security score.” Security, availability, decentralization, and trust remain separate qualitative or explicitly parameterized dimensions.
- Distributed simulation, cloud deployment, databases, authentication, and multi-user dashboard hosting.
- Empirical transaction traces unless provenance, licensing, preprocessing, and privacy are approved.

## 3. Architecture and module responsibilities

Dependency direction is one-way: domain models -> simulator/strategies -> experiments -> adapters/UI. The dashboard never owns benchmark logic.

| Module | Responsibility |
|---|---|
| `config` | Typed, validated, versioned configuration; reject impossible units/ranges and unknown fields. |
| `domain` | Immutable transaction, batch, publication request/result, event, and run-result records. |
| `workload` | Generate or load a workload trace; derive payload bytes deterministically; produce a workload fingerprint. |
| `batching` | Maintain the transaction buffer and close batches by count, byte, or timer rules. |
| `da/base` | Strategy interface: encoded payload, billable units, service demand, publication result, and assumptions metadata. |
| `da/ethereum_calldata` | Byte accounting, selected gas schedule, transaction overhead, and ETH/fiat conversion inputs. |
| `da/compressed_calldata` | Deterministic zlib encoding followed by the identical calldata accounting path. |
| `da/external_mock` | Configurable fee, bandwidth, latency, finite capacity, availability, retries, and trust labels. |
| `engine` | Priority event queue, stable tie-breaking, state transitions, resource queues, termination/drain policy. |
| `metrics` | Per-transaction and per-batch metrics, aggregation, confidence intervals, and invariants. |
| `experiments` | Scenario matrix, paired repetitions, run manifests, output layout, and resumable orchestration. |
| `io` | YAML loading; schema-versioned CSV/JSON/Parquet-like boundaries if later justified. |
| `cli` | Validate config, generate workload, run experiment, summarize, and export. |
| `dashboard` | Later read/run adapter and Plotly views; no duplicate formulas. |

Recommended dependencies for the MVP: standard library (`dataclasses`, `heapq`, `hashlib`, `json`, `zlib`), NumPy, Pandas, PyYAML, Pydantic (or strict dataclass validation), pytest, Streamlit, and Plotly. SimPy is not necessary initially: a small explicit event kernel is easier to audit and validate for this narrow model. SciPy should be added only if a chosen confidence-interval method requires it.

## 4. Concrete simulation model

### 4.1 Entities and units

- Transaction: `tx_id`, arrival time in seconds, logical size in bytes, deterministic byte payload, and workload metadata.
- Batch: ordered transaction IDs, open/close times, raw serialized payload, strategy-encoded payload, and close reason.
- Publication: enqueue, service-start, service-end, confirmation, attempt number, fee, and outcome.
- All internal times use seconds, sizes use bytes, gas uses integer gas units, and currency values carry explicit units (wei, ETH, or configured mock currency).

The batch serialization format must be fixed and documented. The initial proposal is concatenated transaction records with a configurable or fixed per-transaction length prefix. Raw payload bytes include this framing; “sum of transaction bytes” is reported separately so framing is never hidden.

### 4.2 Arrival and batching

Default arrivals use a seeded Poisson process (exponential interarrival times). A deterministic fixed-rate process and trace-driven arrivals are supported for validation. Transaction sizes use a configured fixed, categorical, or bounded distribution. Byte content is generated from a named model because zero-byte frequency and compressibility directly affect calldata cost.

The batcher accepts arrivals in timestamp/ID order. A batch closes when the first of these occurs:

1. maximum transaction count is reached;
2. maximum raw bytes would be reached according to the documented admission rule; or
3. the oldest included transaction reaches the maximum batch wait.

Admission is now fixed: if the next transaction would exceed remaining capacity, the current non-empty batch closes and that transaction becomes the first member of the next batch. A transaction whose framed record is individually larger than the maximum batch byte capacity is rejected with an explicit reason. It is never split or silently discarded.

The same closed logical batch is given to all DA strategies. Compression does not alter batch boundaries in the baseline experiment; otherwise a compressed strategy could gain an unfair batching advantage.

### 4.3 Resource and queue model

Each strategy has a FIFO publication resource with finite service capacity. A publication request enters a queue, begins service when the resource is free and capacity permits, then becomes published and later confirmed/available. A strategy may expose one or more concurrent service slots, defaulting to one.

- Ethereum calldata capacity is modeled with a configurable per-block DA gas budget, block interval, and inclusion/confirmation delay. The publication consumes the modeled gas budget; a request that exceeds a block's usable budget is rejected as invalid rather than silently split. This is a controlled abstraction, not a mainnet block builder.
- External DA service time is `fixed_service_time + encoded_bytes / bandwidth_bytes_per_second`, with optional seeded jitter. Its queue is finite or explicitly unbounded. Full-queue behavior is configurable and reported (reject or wait upstream).
- Availability is an outcome model, not proof of actual data availability. With independent attempt probability `p_available`, a failed attempt follows the configured bounded retry/backoff policy or terminates as failed. Correlated failure is deferred.

### 4.3.1 Latency event semantics

Every timestamp is an event boundary, and every interval is half-open `[start, end)` to prevent overlap or double-counting:

- **Batching starts** at the transaction's `arrival_time`, when the batcher can first accept it. **Batching ends** at `batch_close_time`, when a count, byte, or timer rule freezes membership.
- **Publication queueing starts** at `publication_enqueue_time`. In the baseline this equals `batch_close_time`. **Queueing ends** at `service_start_time`, when capacity is reserved. Queue time includes waiting for the next eligible Ethereum block slot; it excludes actual publication service.
- **Publication service starts** at `service_start_time` and **ends** at `publication_end_time`. For Ethereum, service represents consumption/inclusion in the selected block slot; block waiting belongs only to queueing. For external DA, service contains the configured base service latency plus `encoded_bytes / bandwidth` and optional jitter exactly once.
- **Confirmation starts** at `publication_end_time` and **ends** at `confirmation_time`. It contains only the separately configured post-publication confirmation/finality delay. It never repeats Ethereum block waiting or external DA base service latency.

Simplified state meanings:

- **Published**: the DA service accepted and durably recorded the payload according to that strategy's model. It is not yet necessarily confirmed/final.
- **Included**: Ethereum-specific synonym for published: the calldata transaction was placed in a modeled block and consumed that block slot's gas budget.
- **Confirmed**: the configured post-inclusion/post-publication confirmation delay elapsed without a terminal failure. This is a modeled confidence threshold, not Ethereum consensus finality unless a future profile explicitly models it.
- **Available**: the modeled DA availability check succeeded after publication (and any configured retry). For Ethereum calldata in the MVP, successful inclusion implies modeled availability; for mock external DA it is a Bernoulli outcome. This is not data availability sampling or an adversarial guarantee.

The baseline completion time is `max(confirmation_time, availability_time)` if those events are modeled separately. An implementation that makes availability part of service must not add the same delay again after publication.

Congestion claims require sustained utilization near or above capacity, visible queue growth, and an explicit drain policy. Every run has a measurement window and either (a) drains accepted work after arrivals stop or (b) truncates at a declared horizon; both accepted and unfinished counts are reported.

### 4.4 State transitions

```text
GENERATED -> ARRIVED -> BUFFERED -> BATCHED -> PUBLICATION_QUEUED
          -> SERVICE_STARTED -> PUBLISHED -> CONFIRMED/AVAILABLE -> COMPLETED
                                      \-> RETRY_QUEUED -> ...
                                      \-> FAILED
```

Rejected transactions/publications transition to a terminal `REJECTED` state with a reason. Events at identical timestamps are ordered by a documented stable priority and monotonic sequence number, so results do not depend on hash iteration or platform scheduling.

### 4.5 Ethereum calldata accounting

The simulator uses named, versioned profiles and writes the selected profile into every result manifest.

For the EIP-2028 byte schedule:

```text
T = zero_bytes + 4 * nonzero_bytes
calldata_gas = 4 * T = 4 * zero_bytes + 16 * nonzero_bytes
```

Supported MVP scope is deliberately narrow: a single ordinary, non-contract-creation Ethereum transaction with no access list, authorization list, initcode, or blob fields. `execution_gas_used` is EVM execution gas after refunds, exactly as defined by EIP-7623. Transaction envelope encoding bytes are not separately treated as calldata. Unsupported transaction shapes must be rejected or modeled later under a new named profile.

For this supported transaction, EIP-2028 accounting is:

```text
gas_used = 21,000 + 4 * T + execution_gas_used
```

The EIP-7623-aware profile applies the official transaction-total floor exactly:

```text
gas_used = 21,000 + max(
    4 * T + execution_gas_used,
    10 * T
)
```

The EIP-7623 floor is therefore not added on top of ordinary calldata and execution gas. It replaces the inner term only when `10 * T` is greater. Separately, transaction validity requires the gas limit to cover both intrinsic gas and `21,000 + 10 * T`; gas-limit validation is not the same quantity as final gas used because EIP-7623 notes that valid executions can finish below the reserved floor in refund-sensitive cases. The MVP calculates gas used for an already-valid supported transaction and exposes the minimum floor gas limit; it does not simulate gas-limit failure or refund counters.

The EIP-7623-aware profile is the default. Constants are protocol-derived from EIP-2028 and EIP-7623 and remain named profile data, not unexplained magic numbers.

Hand-calculated golden cases required before implementation:

| Calldata | `T` | Execution gas | EIP-2028 gas used | EIP-7623 gas used | Reason |
|---|---:|---:|---:|---:|---|
| empty | 0 | 0 | 21,000 | 21,000 | No calldata or execution. |
| `00` | 1 | 0 | 21,004 | 21,010 | Floor binds. |
| `ff` | 4 | 0 | 21,016 | 21,040 | Floor binds. |
| `00ff` | 5 | 0 | 21,020 | 21,050 | Floor binds. |
| `ff` | 4 | 24 | 21,040 | 21,040 | Break-even: `16 + 24 = 40`. |
| `ff` | 4 | 25 | 21,041 | 21,041 | Execution-dominant; floor does not bind. |

Cost conversions are:

```text
cost_wei = gas_used * effective_gas_price_wei
cost_eth = cost_wei / 10^18
cost_fiat = cost_eth * configured_eth_fiat_price
```

Gas price and ETH/fiat price are illustrative inputs unless a dated, cited external dataset is deliberately imported. Fiat results are optional and never treated as protocol constants. Batch transaction envelope bytes are not charged per byte in the simplified formula unless a later, explicitly validated serialization model includes them; the 21,000 base and configured overhead are reported separately.

Compressed calldata runs `zlib.compress(raw_payload, level=<configured>)` using recorded Python/zlib versions. Billable zero/nonzero byte counts are measured on the actual compressed byte string, not estimated from a compression ratio. Compression CPU time may be measured as a host-specific diagnostic but is excluded from simulated latency by default to preserve deterministic results.

### 4.6 Main modeled bottlenecks

- Batching: low load or large batch targets increase waiting time.
- Ethereum publication: block-aligned capacity and gas budget create a queue at high offered load.
- External DA: bandwidth, service slots, queue capacity, base latency, failures, and retry backoff.
- Payload characteristics: zero-byte fraction changes calldata gas; repeated structure changes compression ratio.
- Oversized batch: explicit rejection exposes a bad configuration rather than creating impossible throughput.

## 5. Metric definitions and formulas

Let the measurement interval be `[t0, t1]` with duration `D = t1 - t0`; `N_arrived` is arrivals in the interval, `N_completed` is those reaching the terminal success state under the declared drain/censoring policy.

| Metric | Definition |
|---|---|
| Offered transaction rate | `N_arrived / D` transactions/s. Also report configured rate and realized rate. |
| Completed throughput | `N_completed / D_throughput` transactions/s, where the denominator policy (arrival window or makespan) is named. The primary result uses measurement-window completions; drained makespan throughput is secondary. |
| Goodput bytes | Sum of original logical transaction bytes completed / denominator seconds. |
| Publication throughput | Successful batches / denominator seconds and encoded bytes published / denominator seconds. |
| Batching latency | `batch_close_time - tx_arrival_time`. |
| Publication queue latency | `service_start_time - publication_enqueue_time`. |
| Service latency | `publication_end_time - service_start_time`. |
| Confirmation latency | `completion_time - publication_end_time`. |
| End-to-end latency | `completion_time - tx_arrival_time`; equals batching + queue + service + confirmation under the baseline state model. |
| Per-batch cost | Strategy fee for one publication attempt or all attempts; both are recorded. |
| Cost per completed transaction | Total successful-run publication cost, with retry costs included per policy, / `N_completed`. Failed and unfinished work is reported separately to prevent survivor bias. |
| Cost per original KiB | Total publication cost / `(completed original bytes / 1024)`. |
| Raw DA overhead bytes | `serialized_raw_batch_bytes - sum(logical_tx_bytes)`. |
| Encoded DA overhead ratio | `encoded_bytes / sum(logical_tx_bytes)`; values below 1 are possible under compression. |
| Compression ratio | `encoded_bytes / raw_serialized_bytes`; savings = `1 - ratio`. |
| Gas overhead | `base_gas + execution_gas + configured_overhead_gas + floor_increment`, separately from byte-schedule gas. |
| Resource utilization | Busy service time / resource-observation time, with capacity/slotted semantics documented. |
| Queue depth | Time-weighted mean, maximum, and selected percentiles of queued publications. |
| Completion ratio | `N_completed / N_arrived`; also report rejected, failed, and censored/unfinished ratios. |
| Availability success | Successfully available publications / attempted logical publications, plus attempt-level success and retry count. |

Latency and cost distributions report count, mean, standard deviation, median, p90, p95, and p99 when sample size supports the percentile. Across repetitions, report the mean and a 95% confidence interval or bootstrap interval with method and seed recorded. Never pool dependent per-transaction observations and pretend they are independent experimental repetitions.

## 6. Fair experimental design

### 6.1 Pairing and controls

- Generate each `(scenario, repetition)` workload once, persist its hash, and replay it unchanged across all strategies.
- Use separate, derived random streams for workload, service jitter, and availability so adding a random draw in one component cannot perturb arrivals.
- Keep batch policy, raw serialization, duration, warm-up, and termination policy identical across strategies in the primary comparison.
- Vary one principal factor at a time for explanatory sweeps; use a documented factorial subset for interactions.
- Randomize execution order where host timing is measured, though simulated outputs must be order-independent.
- Pin configuration schema, code revision when available, Python/zlib versions, platform metadata, and all seeds.

### 6.2 Primary experiments

The report prioritizes exactly three primary experiments:

1. **Transaction load sweep**: offered rate across underload, near-capacity, and overload regimes while holding batch policy and payload model fixed.
2. **Batch size sweep**: transaction-count and/or raw-byte batch limits at a fixed representative load, exposing cost amortization versus batching latency.
3. **Data compressibility sweep**: high-entropy, zero-heavy, repeated-structure, and mixed payloads at fixed size/load, separating zero-byte calldata pricing from compression effects.

### 6.3 Secondary sensitivity analyses

First calibrate nominal capacity from configuration, then set load points relative to the slowest or strategy-specific modeled capacity rather than hardcoding a desired outcome.

- Load sweep: approximately 25%, 50%, 80%, 100%, 120%, and 160% of nominal service capacity, plus a fixed absolute transaction-rate comparison shared by all strategies.
- Transaction size: small, medium, large, and a realistic mixed distribution (exact byte values require approval or cited trace evidence).
- Byte content: high entropy, zero-heavy, repeated-structure, and mixed; this separates calldata zero-byte effects from compressibility.
- Batch policy: small/low-delay, balanced, and large/high-delay.
- Fee sensitivity: low/base/high gas-price profiles and external per-byte/fixed-fee profiles, clearly illustrative.
- External DA sensitivity: bandwidth, base latency, independent availability, retry limit, and service concurrency.
- Ethereum accounting sensitivity: EIP-2028 byte schedule with and without the EIP-7623 transaction-total floor profile as explicitly labeled protocol scenarios.

Use at least 10 seeded repetitions for stochastic smoke experiments and target 30 for reported comparisons, subject to runtime and an empirical interval-stability check. Deterministic formula tests require no repetitions. Warm-up and run duration are chosen after queue-stability pilot runs, not to hide overload.

Fee levels, external DA bandwidth/base latency/availability/retries, and Ethereum accounting profile comparisons are secondary sensitivity analyses. They must not displace the three primary experiments.

### 6.4 Required plots/tables in later phases

- Offered load versus completed throughput and completion ratio.
- Offered load versus median/p95 end-to-end latency, with component breakdown.
- Offered load versus cost/transaction and cost/original KiB.
- Original versus encoded bytes, compression ratio, and zero/nonzero composition.
- Queue depth/utilization versus time for representative underload and overload cases.
- A non-ranked assumptions matrix: publication location, data-retention assumption, verification model, failure model, operator/validator assumption, and what the simulator does not capture.

## 7. Risks, trust limitations, and validation

| Risk | Consequence | Mitigation/validation |
|---|---|---|
| Synthetic bytes compress unrealistically | Misleading compressed-calldata savings | Publish byte generator; include entropy/repetition scenarios; later compare with a cited trace. |
| Incorrect or outdated Ethereum gas profile | Wrong cost conclusions | Named profiles, protocol citations, hand-calculated golden cases, and no silent “current mainnet” claim. |
| Confusing calldata and blobs | Category error | Separate terminology and model; blobs remain deferred. |
| External DA mock presented as a real network | Unsupported claims | Label every result “mock external DA”; use illustrative configs and a visible assumption manifest. |
| Infinite queue masks overload | Unrealistic completion claims | Configurable finite capacity, unfinished/rejected counts, queue trajectories, and stability checks. |
| Drain-after-arrivals inflates throughput | Denominator ambiguity | Publish both window and drained makespan metrics with precise denominator labels. |
| Independent availability exaggerates resilience | Security/availability overclaim | State that Bernoulli availability omits correlated/adversarial failures; sensitivity only. |
| Compression CPU/runtime noise harms reproducibility | Latency varies by machine | Simulated compression delay off by default; measured CPU time marked host-specific. |
| Tail percentiles from small samples | Unstable latency claims | Report sample counts, repetitions, interval method, and suppress/flag underpowered percentiles. |
| Strategy-specific randomness breaks pairing | Unfair comparison | Independent named RNG streams and workload hashes. |
| Security collapsed into performance | False superiority claim | Separate qualitative dimensions; no composite ranking without an approved, defended model. |

### Required invariants

1. Transaction conservation: `generated = completed + failed + rejected + unfinished` at the declared terminal time.
2. Batch conservation: every accepted transaction belongs to exactly one batch and appears once, unless explicitly still buffered.
3. Byte accounting: raw serialized bytes equal framing plus transaction payload bytes; strategy encoded bytes equal the actual bytes passed to its cost/service model.
4. Calldata accounting: zero count + nonzero count equals encoded length; recomputed gas equals recorded gas for the selected profile.
5. Cost accounting: run cost equals the sum of attempt costs; per-transaction allocations sum to batch/run totals within declared rounding rules.
6. Temporal ordering: arrival <= batch close <= enqueue <= service start <= publish <= confirmation for successful records.
7. Capacity: service never exceeds configured concurrent slots or per-period budget.
8. Determinism: same config, seed, workload, and software version yield byte-identical canonical result data (excluding explicitly non-deterministic host timing/metadata).
9. Cross-strategy fairness: logical transaction IDs, arrival times, sizes, payload hashes, and batch membership match for the primary paired comparison.
10. Latency decomposition: end-to-end equals the sum of its recorded components within floating-point tolerance.

Validation combines hand-worked fixtures, boundary tests, property/invariant tests over many seeds, overload tests, deterministic replay, and one end-to-end golden experiment. Analytical queue limits are used where the simplified service model permits; otherwise event traces are audited.

## 8. Proposed repository structure

```text
SC6109project/
  README.md
  pyproject.toml
  configs/
    baseline.yaml
    scenarios/
  docs/
    architecture.md
    methodology.md
    assumptions.md
    validation.md
  src/da_rollup_bench/
    __init__.py
    config.py
    domain.py
    workload.py
    batching.py
    engine.py
    metrics.py
    experiments.py
    io.py
    cli.py
    da/
      base.py
      ethereum_calldata.py
      compressed_calldata.py
      external_mock.py
  dashboard/
    app.py
    pages/
  tests/
    unit/
    property/
    integration/
    fixtures/
  results/
    .gitkeep
  scripts/
    verify_reproducibility.py
```

Generated result directories should be ignored by Git except for a small, reviewed reference fixture. Each run directory will contain the resolved config, manifest, workload hash, raw records, summaries, and an error log if incomplete.

## 9. Independently testable milestones

1. **Configuration contract**: schemas, units, defaults, invalid-input tests, and canonical config hashing.
2. **Workload generator**: fixed/Poisson arrivals, size/content models, split RNG streams, trace export/import, deterministic hash tests.
3. **Batcher**: count/byte/timer closing, stable boundary behavior, framing accounting, and transaction conservation.
4. **Calldata calculator**: zero/nonzero golden vectors, base/overhead separation, EIP-7623 floor binding cases, and cost conversion.
5. **Compression strategy**: actual zlib bytes, version metadata, decompression round-trip, zero/nonzero recount, and deterministic fixtures.
6. **External DA service**: bandwidth/service-time formula, FIFO queue, finite capacity, seeded failures, retry/backoff, and terminal states.
7. **Event engine**: deterministic tie order, resource capacity, drain/truncate policies, state-machine guards, and latency decomposition.
8. **Metrics and invariants**: exact small examples, percentiles, denominator labels, censored work, confidence intervals, and accounting checks.
9. **Experiment pipeline and CLI**: paired matrix run from YAML to raw/summary outputs; repeat run comparison.
10. **Dashboard**: load existing results and optionally launch runs through the same orchestration API; filters, plots, assumptions, and export.
11. **Documentation and final verification**: reproducibility walkthrough, limitations, protocol citations, baseline artifact, and clean-environment test.

Each milestone should merge only when its focused tests pass. Milestones 1–9 establish the headless scientific core before dashboard work.

### MVP acceptance criteria

The minimum complete deliverable is independent of research-quality extensions. The MVP is accepted only when all of the following are true:

1. All three strategies run through the same headless pipeline: uncompressed calldata, zlib-compressed calldata, and generic mock external DA.
2. A resolved configuration plus seed reproduces the same logical workload, batch membership, and canonical output data.
3. Cost, byte, throughput, completion, and decomposed latency metrics pass hand-calculated fixtures and conservation/accounting invariants.
4. The three primary experiments run from committed illustrative configs and produce raw data plus summaries.
5. Essential plots show throughput, end-to-end/component latency, cost, DA bytes/overhead, and completion ratio, with units and assumptions visible.
6. Core unit and integration tests pass in a clean supported Python environment, and the actual command/result is documented.
7. README, methodology, assumptions, and limitations explain simulated versus measured/protocol-derived values and allow reproduction from the CLI.
8. No live network, Solidity contract, node, paid API, or claim of real external-DA performance is required.

Research-quality extensions include empirical traces, more repetitions or advanced interval methods, correlated/adversarial failures, additional protocol profiles, EIP-4844, live validation datasets, and richer security analysis. Their absence does not make the MVP incomplete.

## 10. Resolved decisions and remaining implementation assumptions

Approved: both gas profiles with EIP-7623-aware default; block-slot gas-budget queue; next-batch admission and oversized rejection; illustrative workload defaults; generic low/base/high external DA profiles; independent Bernoulli failures with bounded retries; 10 development and target 30 final repetitions; explicit separate currency units; deferred EIP-4844; and SC6019 documentation identity without renaming the workspace.

Remaining assumptions to validate during implementation are limited to concrete illustrative parameter values, exact canonical output schema, and later calibration of run duration/warm-up. None may be presented as observed network data.

## 11. Protocol references used for the model

- Ethereum Improvement Proposal 2028, “Transaction data gas cost reduction”: https://eips.ethereum.org/EIPS/eip-2028
- Ethereum Improvement Proposal 7623, “Increase calldata cost”: https://eips.ethereum.org/EIPS/eip-7623
- Ethereum transaction documentation: https://ethereum.org/developers/docs/transactions/

These references define protocol-derived accounting concepts only. Experiment fee levels, external DA parameters, workloads, and all simulator outputs remain explicitly assumed or synthetic unless later backed by a dated dataset.
