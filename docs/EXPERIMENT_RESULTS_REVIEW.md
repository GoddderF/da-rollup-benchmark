# Milestone 10 Experimental Results Review

Date: 2026-10-12

## Scope and evidence

The simulator, metrics, statistics, orchestration, and persisted artifacts were inspected directly. The complete pre-change suite passed 84 tests. Each original development sweep was then executed unchanged with 10 independent run-level repetitions per scenario and three paired strategies (90 runs per sweep). Outputs are under `results/milestone10-review/original`.

Two minimal matrix corrections were justified by those results:

- The transaction-load points `2, 10, 25 TPS` were all underloaded relative to the configured Ethereum resource abstraction. They were changed to illustrative `25, 250, 400 TPS` points, which bracket its observed underload, near-capacity, and overload regions.
- The batch limits `10, 50, 100` made 50 and 100 almost identical because a 2-second timer at approximately 10 TPS closed both first. They were changed to `5, 20, 100`, representing count-bound, boundary-region, and timer-bound behavior.

No capacity value was calibrated to force a preferred strategy outcome. The base 30,000,000-gas/12-second Ethereum abstraction, transaction model, and mock-DA configuration were not changed. The compressibility matrix was already informative and was left unchanged. Revised development outputs are under `results/milestone10-review/revised`.

No significant simulator correctness issue was found. All persisted runs passed transaction/batch conservation, capacity, temporal-ordering, and latency-decomposition validation before being accepted by the orchestrator.

## Actual trends

### Transaction load

At mean offered loads of approximately 24.9, 249.6, and 399.9 TPS:

- Raw Ethereum resource utilization increased from 7.0% to 68.7% to 94.3%.
- Raw Ethereum primary in-window throughput increased from 19.4 to 199.3 TPS, then flattened at exactly 240 TPS in the 400-TPS scenario. Its P95 latency rose from 12.8 seconds to 27.0 seconds in overload, and average publication queue depth rose to 46.3.
- Mock external DA remained below 7.1% utilization and achieved 24.6, 248.3, and 398.5 TPS within the window under its deliberately generous illustrative capacity.
- Drain mode eventually completed every transaction, so `completion_ratio = 1` is not evidence that overload was absent. Primary throughput counts only completions before 60 seconds; post-horizon drain completions are excluded. The dashboard therefore shows throughput, latency, queueing, utilization, and terminal counts together.

Ethereum raw and compressed throughput/latency are identical for the high-entropy workload because both fit the same block-slot schedule. High-entropy zlib encoding is not beneficial here and uses slightly more gas. This is a meaningful negative result, not a defect.

### Batch size

The revised points produce distinct batching regimes:

- At 5 transactions, mock-DA P95 latency is about 0.66 seconds, but more publications raise raw Ethereum gas to about 7.12 million per run.
- At 20 transactions, mock-DA P95 latency is about 1.91 seconds and raw Ethereum gas falls to 5.58 million.
- At 100 transactions, the timer dominates; mock-DA P95 latency is about 2.04 seconds and raw Ethereum gas is about 5.42 million.

Ethereum P95 latency remains dominated by 12-second block slots. The 20- and 100-transaction points are closer than the 5-transaction point but no longer effectively duplicate one another.

### Compressibility

- High-entropy input slightly expands with zlib (`encoded/raw ≈ 1.0022`) and compressed publication uses about 26,572 more gas per run than raw on average.
- The 80%-zero workload compresses to about 40.8% of serialized size, but compressed calldata still uses slightly more gas than raw. The raw representation's many zero bytes are already cheap under calldata accounting, whereas compressed bytes are predominantly non-zero. Byte compression is therefore not equivalent to gas savings.
- Repeated input compresses to about 1.45% of serialized size. Mean gas falls from about 5.41 million to 0.676 million per run; the paired raw-minus-compressed difference is about 4.73 million gas with a 95% CI of 4.61–4.84 million.

These outcomes validate the need to display bytes, calldata gas, and cost separately.

## Internal consistency

- Offered rate uses generated transactions divided by the configured 60-second horizon.
- Primary throughput uses completions strictly within that horizon. Drained makespan throughput has a separate denominator and is not substituted into primary plots.
- Costs include every publication attempt, including failed attempts. Cost per completed transaction is undefined for zero completions.
- Retry latency is decomposed into cumulative queue, service, backoff, and confirmation components by the engine; the validation invariant requires their non-overlapping sum to equal end-to-end latency.
- Ethereum costs use wei; mock external DA costs use `MOCK_DA_UNIT`. Paired comparisons intersect metric names, so incompatible unit-qualified cost keys are never paired.
- Resource utilization uses consumed/available Ethereum gas or external busy-server time/concurrency/observation time. It is not a cross-resource physical equivalence.

## Statistical interpretation

Each reported confidence interval is a two-sided 95% Student t interval over 10 independent complete simulation runs. The unit of replication is the run, never an individual transaction. Paired comparisons first subtract strategies within the same workload repetition, preserving workload pairing.

Intervals describe stochastic run-to-run variability only. They do not represent simulator model uncertainty, parameter uncertainty, real-network variability, or a security confidence claim. Several deterministic-capacity outputs have zero-width intervals (for example, 240 TPS in the overloaded Ethereum scenario); that means every modeled repetition reached the same slot-limited result, not that real-world uncertainty is zero. Ten repetitions are suitable for development visualization but statistically modest; final results should use the approved 30-repetition preset and check stability.

## Unsuitable or potentially misleading views

- The original load sweep and original 50/100 batch-size comparison should not be used in the demonstration; they are preserved only as review evidence.
- Completion ratio alone is misleading under drain, because post-horizon completions make it 1 even when in-window throughput is saturated.
- Mock external DA performance is a consequence of illustrative capacity and independent Bernoulli availability assumptions, not evidence about any real network.
- Zero failures/rejections in these primary sweeps do not validate failure handling; deterministic regression scenarios cover retries, exhausted retries, saturation, and rejection.
- ETH/wei and `MOCK_DA_UNIT` cannot be compared economically and must not share a monetary axis.
- The high-entropy and zero-heavy results show that compression ratio must not be presented as calldata gas savings without the separately calculated gas result.

## Dashboard data contract and limitations

The dashboard is read-only and loads versioned manifests plus existing run-level and aggregate outputs. It does not run simulations, calculate confidence intervals, or alter artifacts. Missing metrics are shown as unavailable, and zero-offer ratios remain undefined rather than causing division errors.

Remaining limitations include illustrative parameters, synthetic workloads, no empirical calibration, independent availability failures, no correlated/adversarial failure model, no blob publication, and no direct security or currency equivalence. Milestone 10 does not constitute the final project analysis.
