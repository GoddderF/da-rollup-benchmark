# Milestones 7-8 Implementation

Date: 2026-10-12

## Event model

The engine is single-threaded and deterministic. Its only event ordering key is:

```text
(simulation_timestamp, event_priority, monotonic_sequence_number)
```

No wall-clock time or compression CPU measurement enters simulated time. Equal-time priority is:

1. external service completion;
2. confirmation completion;
3. Ethereum block slot;
4. batch timeout;
5. transaction arrival;
6. retry ready;
7. publication enqueue; and
8. measurement horizon.

This means capacity is released before same-time arrivals, a batch produced exactly at a block boundary waits for the next slot, and an active batch times out before a transaction arriving exactly at its deadline.

## Resolved integration conflicts

1. **Offline batcher:** `StatefulBatcher` adds `on_transaction`, tokenized `on_timeout`, and `flush`. Stale timer generations are ignored. The original offline function remains as a reference and has a regression comparison.
2. **Raw calldata:** `RawCalldataStrategy` is a thin `PreparedPublication` wrapper around the existing gas calculator. It does not duplicate accounting.
3. **Retry capability:** only the external resource adapter invokes mock-specific outcome/backoff methods. Ethereum strategies do not receive meaningless retry APIs.
4. **Admission:** the engine checks `PreparedPublication.admissible` before queueing or charging an attempt. Oversized Ethereum gas demand is checked against the configured per-slot budget.
5. **Profile scope:** the engine consumes one resolved external profile. It does not select low/base/high scenarios.
6. **Floating time:** deterministic replay is guaranteed for the same configuration and recorded runtime. Cross-runtime floating/RNG bit identity remains outside the guarantee.

No conflict required a significant change to the approved architecture.

## Resource semantics

### Ethereum

The block-slot gas budget is an explicit simulation abstraction, not an Ethereum mainnet DA quota. The queue is strict FIFO and finite. Each slot admits as many head publications as fit. If the head cannot fit the remaining budget, processing stops and the head carries to the next slot. A request larger than the full budget is rejected without an attempt cost.

Inclusion is an instantaneous publication service event at the slot timestamp. Waiting for the slot is queue latency. Confirmation begins at inclusion and is separately configured. Each result records gas consumed per processed slot and total available slot budget.

### Mock external DA

The resource owns one finite FIFO waiting queue and a configurable number of identical service slots. Queue capacity counts waiting requests, not active services. Service time is exactly the strategy-provided fixed delay plus bytes divided by bandwidth.

Attempt cost is incurred when service starts, including an attempt still active at truncation. Availability is evaluated at service completion. A failed attempt enters retry backoff, then competes for the same queue again. Retry queue saturation is terminal rejection; exhaustion is terminal failure.

## Non-overlapping latency accounting

For a completed transaction:

```text
end_to_end
  = batching
  + sum(queue_wait_per_attempt)
  + sum(service_time_per_attempt)
  + sum(retry_backoff)
  + final_confirmation
```

- Batching: arrival to logical batch close.
- Queue: each attempt's enqueue/retry-ready time to its service start or Ethereum inclusion.
- Service: external service start to completion for every attempt; zero-duration for Ethereum slot inclusion.
- Retry backoff: failed service completion to retry-ready.
- Confirmation: final successful service/inclusion to confirmation completion.

The engine validates this equality within a strict floating tolerance.

## Termination and throughput

The measurement window is half-open `[0, horizon)`. Primary completed throughput uses only completions strictly inside that window divided by the window duration. Post-horizon drain completions are excluded.

- `truncate`: process same-time events preceding the horizon event, flush buffered batching state, then classify nonterminal work as unfinished.
- `drain`: stop/flush at the horizon and continue already accepted work until terminal, subject to `max_events`.

Drained makespan throughput is total completions divided by `run_end_time`, where `run_end_time = max(measurement horizon, final meaningful terminal event)`. Failed, rejected, and unfinished counts are always reported with throughput.

## Metrics and validation

Metrics are derived from immutable outcomes and attempt records:

- offered rate and primary/drained throughput;
- completion ratio and terminal counts;
- latency components plus p50/p90/p95/p99 end-to-end latency;
- per-unit attempted costs and per-completed-transaction costs;
- attempt, failed-attempt, retry, publication rejection, and unfinished counts;
- logical, serialized, encoded, and attempted encoded bytes;
- time-weighted/maximum waiting queue depth;
- external busy-server utilization;
- Ethereum consumed/available gas utilization and per-slot gas.

Wei and `MOCK_DA_UNIT` remain separate dictionary keys and are never converted or summed.

Validation checks transaction and batch conservation, unique membership, resource capacity, temporal ordering, latency decomposition, and cross-strategy workload/batch equality.

## Remaining limitations

- The engine runs one strategy per run; scenario matrix orchestration is Milestone 9.
- Ethereum uses a configurable fixed slot interval and budget, without base-fee dynamics, competing L1 traffic, reorgs, or proposer behavior.
- Strict FIFO may cause deliberate head-of-line blocking.
- Mock availability attempts are independent and exclude correlated/adversarial failures.
- Queue capacity counts waiting requests only for external DA; active services are separately bounded by concurrency.
- Percentile summaries are descriptive and have no confidence intervals yet.
- Run manifests, CSV/JSON persistence, repeated-run statistics, and CLI orchestration remain Milestone 9 work.

