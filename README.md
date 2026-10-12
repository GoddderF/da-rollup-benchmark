# SC6019 Data Availability-Aware Rollup Benchmarking Platform

This repository currently implements Milestones 1–4 of the approved plan:

1. strict, versioned YAML configuration;
2. deterministic synthetic workload generation with independent random streams;
3. transaction batching and canonical length-prefix serialization; and
4. Ethereum calldata gas accounting under EIP-2028 and EIP-7623-aware profiles.

The defaults are illustrative rather than measurements of a live rollup. No blockchain node, live network, external DA strategy, simulation engine, experiment runner, or dashboard is implemented yet.

## Run the tests

From PowerShell, with Python 3.11 or newer and the project test dependencies available:

```powershell
$env:PYTHONPATH = (Resolve-Path 'src')
python -m pytest
```

The baseline input is `configs/baseline.yaml`. The EIP-7623-aware profile is the default and supports only an ordinary, non-contract-creation transaction with no access list, authorization list, initcode, or blob fields. Execution gas means EVM execution gas after refunds. See `PHASE_0_PLAN.md` for formulas, latency semantics, experiments, acceptance criteria, and deferred scope.

