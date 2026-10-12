# SC6019 Data Availability-Aware Rollup Benchmarking Platform

This repository currently implements Milestones 1–6 of the approved plan:

1. strict, versioned YAML configuration;
2. deterministic synthetic workload generation with independent random streams;
3. transaction batching and canonical length-prefix serialization; and
4. Ethereum calldata gas accounting under EIP-2028 and EIP-7623-aware profiles;
5. deterministic zlib-compressed calldata accounting; and
6. generic mock external-DA publication requirements, availability, and retry policies.

The defaults are illustrative rather than measurements of a live rollup. The mock external DA is not a real-network model. No blockchain node, live network, simulation engine, experiment runner, metrics pipeline, or dashboard is implemented yet.

## Run the tests

From PowerShell, with Python 3.11 or newer and the project test dependencies available:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src')
python -m pytest
```

The baseline input is `configs/baseline.yaml`. The EIP-7623-aware profile is the default and supports only an ordinary, non-contract-creation transaction with no access list, authorization list, initcode, or blob fields. Execution gas means EVM execution gas after refunds. See `PHASE_0_PLAN.md` for formulas, latency semantics, experiments, acceptance criteria, and deferred scope.
