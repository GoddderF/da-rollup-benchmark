# Proposed Milestones 7-8 Integration Design

Status: proposal only. No event engine or metrics pipeline is implemented.

## 1. Deterministic event kernel

Use a single-threaded priority queue ordered by `(timestamp, event_priority, sequence_number)`. The sequence number is monotonic and is the final stable tie-breaker. Events and state transitions are immutable records appended to an audit ledger.

Proposed event types:

1. transaction arrival;
2. batch timeout;
3. publication enqueue;
4. Ethereum block slot;
5. external service completion;
6. availability outcome;
7. retry ready;
8. confirmation completion; and
9. run horizon/drain completion.

Tie policy must be explicit. Recommended semantics:

- Resource completion releases capacity before new work at the same timestamp.
- An Ethereum block-slot event runs before a batch timeout or arrival at the same timestamp, so a batch created exactly on a slot boundary waits for the next slot.
- Batch timeout runs before a transaction arrival at the same timestamp, preserving the already-approved half-open timer interval.
- Retry-ready and new enqueue events use stable sequence order after resource releases.

No wall-clock calls, threads, or host CPU measurements enter event time.

## 2. Stateful batcher adapter

The current offline `batch_transactions` function is a deterministic reference but cannot cancel/reschedule timer events. Add a stateful adapter with:

- `on_transaction(transaction, now)`;
- `on_timeout(batch_generation, now)`;
- `flush(now)`; and
- emitted `BatchClosed` or `TransactionRejected` records.

Use a generation token to make stale timeout events harmless. Reuse the current serializer and admission rules. A property/regression test must feed the same trace to both the offline helper and stateful adapter and require identical batches, close times/reasons, and rejections.

## 3. Common strategy preparation

Every closed logical batch retains identical membership and `raw_payload` across strategies. Add a thin raw-calldata strategy adapter around the existing gas calculator. All three strategies then return `PreparedPublication`:

| Strategy | Encoded payload | Capacity unit | Cost unit | Service time |
|---|---|---|---|---|
| Raw calldata | Batch raw bytes | gas | wei | determined by block slots |
| Compressed calldata | zlib bytes | gas | wei | determined by block slots; compression simulation delay is zero |
| Mock external DA | Batch raw bytes | bytes | `MOCK_DA_UNIT` | fixed time + bytes/bandwidth |

The engine owns scheduling. Strategies only encode and calculate immutable requirements/outcomes.

## 4. Ethereum block-slot resource

- Maintain one FIFO queue per Ethereum strategy run.
- At each block slot, reset available DA gas budget to `da_gas_budget_per_block`.
- Reject a publication permanently if its demand exceeds the full per-block budget.
- Recommended MVP policy is strict FIFO without bypass: consume the head if it fits remaining budget; otherwise carry it to the next block. This avoids a hidden size-priority policy but can create head-of-line blocking, which must be reported.
- Inclusion/published time is the slot timestamp in which gas is consumed.
- Confirmation is a separate configurable delay after inclusion. Block waiting is queue time and is never added again as service or confirmation time.

If later allowing within-slot bypass, it must be a named scheduling policy and separate experiment because it changes latency fairness.

## 5. External DA queue and retries

- One FIFO waiting queue with configured request capacity and `service_concurrency` identical servers.
- If a server is free, an admissible enqueue starts immediately; otherwise it waits if queue capacity remains or is rejected as `queue_full`.
- Service duration comes only from `PreparedPublication.service_time_seconds`.
- On service completion, evaluate the deterministic attempt outcome keyed by publication ID and 1-based attempt number.
- A successful attempt becomes published/available, then waits only for a separately configured confirmation delay if one exists.
- A failed attempt incurs that attempt's fee, records an unavailable publication attempt, and schedules `retry_ready` after the strategy backoff if attempts remain.
- A retry re-enters the same queue and is subject to its capacity policy. After the final failure, the logical publication and its transactions become failed.

The strategy exposes the outcome and backoff calculation; the engine owns attempt state and queue events.

## 6. Terminal accounting

Every transaction must be exactly one of:

- completed;
- batching-rejected;
- publication-rejected;
- failed after attempts; or
- unfinished at the declared horizon.

Every logical publication records all attempts. Run termination supports two named modes:

- **truncate**: stop at the horizon and classify buffered, queued, serving, retry-waiting, or unconfirmed work as unfinished;
- **drain**: stop arrivals at the horizon and continue until all accepted work reaches a terminal state, with a safety limit to detect unstable/unbounded scenarios.

Conservation is checked at transaction, batch, logical-publication, and attempt levels.

## 7. Metrics pipeline

Metrics consume the immutable event/attempt ledger; they do not query mutable engine state after the fact.

- Offered rate: arrivals in measurement window / window duration.
- Completed throughput: completions in measurement window / window duration. Drained makespan throughput is separate and labeled.
- Batching latency: batch close - transaction arrival.
- Queue latency: service start/inclusion slot eligibility - publication enqueue.
- External service latency: service completion - service start.
- Ethereum publication service is slot inclusion at a point event; block waiting is queue latency.
- Confirmation latency: confirmation completion - published/included time.
- End-to-end: terminal success - transaction arrival; it must equal the non-overlapping components.
- Cost: sum per-attempt costs, maintaining separate aggregation columns for wei/ETH and `MOCK_DA_UNIT`; never sum unlike units.
- Utilization: Ethereum gas consumed / offered DA gas budget over observed slots; external busy-server time / `(concurrency * observation duration)`.
- Report completion, rejection, failure, retry, and unfinished counts beside throughput/latency to prevent survivor bias.

## 8. Fairness and reproducibility invariants

1. All strategies receive the same workload fingerprint, transaction IDs, arrivals, sizes, payloads, batch membership, and raw serialization.
2. Strategy encoding may change only encoded bytes and derived resource/cost requirements.
3. Availability is keyed by logical publication and attempt so event ordering cannot perturb outcomes.
4. Canonical run manifests contain resolved config, workload hash, Python/zlib versions, code revision when available, and event-priority policy version.
5. Same manifest produces identical canonical event/result data, excluding explicitly host-dependent diagnostics.
6. `generated = completed + rejected + failed + unfinished` with mutually exclusive IDs.
7. Attempt costs sum exactly to logical publication and run costs within each unit.
8. No resource exceeds its gas budget, queue capacity, or concurrency.
9. All timestamps respect the documented state order and latency decomposition.

## 9. Architectural conflicts to resolve before implementation

1. **Batcher shape:** current batching is offline; Milestone 7 needs the stateful adapter described above. Domain records and serialization can remain unchanged.
2. **Raw calldata adapter:** the calculator exists, but it needs the same `PreparedPublication` wrapper used by the other strategies.
3. **Retry capability:** retry/outcome methods are intentionally mock-strategy-specific and are not part of the minimal preparation protocol. The engine should use a dedicated external-DA resource adapter rather than add meaningless retry methods to Ethereum strategies.
4. **Admission ownership:** `PreparedPublication` now preserves admission status. The engine must never schedule an inadmissible request or charge it an attempt fee.
5. **Configuration scope:** one external profile is resolved per run. Scenario orchestration, not the engine, selects low/base/high profiles.
6. **Floating-point time:** deterministic ordering is stable for one recorded Python/runtime, but cross-runtime bit identity for stochastic floating-point arrivals is not promised. Canonical manifests must record runtime versions; an integer-tick time model can be considered if cross-runtime identity becomes a hard requirement.

