# Code Review and Milestones 5-6 Checkpoint

Date: 2026-10-12

## Review scope and conclusions

The implementation and tests for Milestones 1-4 were reviewed directly. The EIP formulas were checked against the official EIP-2028 and EIP-7623 specifications rather than inferred from the project plan.

### Configuration

- Defaults, project identifier, units, strict unknown-field rejection, immutability, and schema versioning are correct.
- Canonical JSON sorts object keys and uses compact separators before SHA-256 hashing.
- A fixed baseline hash is now a regression fixture: `aeb2da17ebeebc73b0e077f2627876111e7f95d1682a80ff2817378505a8e187`.
- Confirmed issue fixed: positive infinity previously satisfied positive numeric constraints. All simulation floats now reject NaN and infinities.
- Decimal is used for mock-DA fees, avoiding binary floating-point currency arithmetic.

### Workload

- Arrival, size, and payload generation use separately derived SHA-256 seeds and independent `random.Random` instances.
- Changing the payload content model cannot change arrivals; this is covered by a regression test.
- Transaction IDs, payloads, IEEE-754 timestamps, and framing are included in the workload SHA-256 fingerprint.
- Stability is guaranteed for the recorded Python implementation/version. Cross-runtime bit-for-bit RNG compatibility is not claimed; manifests must record Python version.

### Batching and serialization

- Count, byte, and timer closure paths are deterministic.
- A transaction arriving exactly at the timer deadline starts the next batch; the older batch closes at the deadline.
- A record that exactly fills byte capacity closes immediately at that arrival timestamp.
- A transaction that would overflow a non-empty batch starts the next batch. Individually oversized records and length-prefix overflow are rejected explicitly.
- Conservation is now tested with interspersed rejections, checking both no loss and no duplication.
- The existing offline batching helper remains useful as a reference implementation. The future event engine needs a stateful batcher adapter so it can schedule/cancel timer events; this is an identified integration task, not a change to batch or transaction records.

### Ethereum calldata accounting

- For the supported non-creation transaction scope, EIP-2028 uses `21000 + 4*T + execution_gas_used`.
- EIP-7623 uses `21000 + max(4*T + execution_gas_used, 10*T)` where `T = zero + 4*nonzero` and execution gas is after refunds.
- The floor is not added to ordinary gas. Existing golden vectors independently specify expected totals for empty, zero, nonzero, mixed, break-even, and execution-dominant cases.
- The implementation intentionally excludes contract creation, access lists, authorization lists, blob fields, gas-limit execution, and explicit refund-counter simulation.

### Test independence

- Configuration tests now use a fixed external digest rather than only comparing the function to itself.
- Gas golden tests use hand-calculated totals from the official formulas.
- Serialization uses fixed byte fixtures and independent round-trip assertions.
- New compression tests independently recompute calldata tokens and the EIP-7623 total from actual zlib bytes.
- Mock DA tests use exact Decimal fee results and hand-calculated service times/backoffs.

## Milestone 5 implementation

- Compresses the exact batch `raw_payload` with zlib and a recorded level/runtime version.
- Immediately decompresses and verifies equality before returning a publication requirement.
- Counts actual compressed bytes and sends those bytes through the existing gas calculator.
- Represents Ethereum capacity demand in gas and monetary cost in wei.
- Sets simulated compression latency to zero. Optional CPU timing is a separate explicitly host-dependent diagnostic and is never inserted into simulated service latency.
- Covers high-entropy-like, all-zero, repeated, and empty byte strings.

## Milestone 6 implementation

- Computes exact mock cost as `fixed_fee + per_byte_fee * payload_bytes` using Decimal.
- Computes service demand as `fixed_service_time + payload_bytes / bandwidth`.
- Exposes payload capacity, queue capacity, and service concurrency without creating a queue or scheduler.
- Uses order-independent SHA-256-derived Bernoulli samples keyed by seed, publication ID, and attempt number.
- Bounds attempts to `1 + max_retries` and exposes exponential retry backoff requirements.
- Carries qualitative trust assumptions without creating a security score.
- Uses the explicit `MOCK_DA_UNIT`, never wei, ETH, gas, or a real-network currency claim.
- Supplies generic illustrative low/base/high presets. Their labels are scenario labels, not security rankings.

## Interface changes

`ProjectConfig` now includes `compression` and `external_da` sections, so the baseline canonical hash changed intentionally. A scheduling-neutral `PreparedPublication` contract was added. It carries encoded bytes, capacity demand/unit, monetary cost/unit, optional service time, and admission status. Both new strategies implement `prepare(publication_id, raw_payload)` and perform no scheduling.

No previously supported function signature was removed. Existing transaction, batch, workload, serialization, and calldata-calculator interfaces remain intact.

