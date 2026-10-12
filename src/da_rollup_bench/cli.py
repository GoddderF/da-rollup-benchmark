"""PowerShell-friendly command-line interface for reproducible simulator runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .artifacts import (
    canonical_hash,
    persist_run_artifacts,
    validate_artifact_directory,
    workload_document,
    write_json,
)
from .config import load_config
from .da.compressed_calldata import CompressedCalldataStrategy
from .da.external_mock import MockExternalDAStrategy
from .da.raw_calldata import RawCalldataStrategy
from .engine import SimulationEngine
from .experiments import (
    expand_scenarios,
    load_experiment,
    resummarize_experiment,
    run_experiment,
    validate_experiment_artifacts,
)
from .metrics import summarize, validate_result
from .workload import generate_workload, workload_fingerprint


def _strategy(name: str, config):
    if name == "raw":
        return RawCalldataStrategy(config.ethereum)
    if name == "compressed":
        return CompressedCalldataStrategy(config.compression, config.ethereum)
    return MockExternalDAStrategy(config.external_da)


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="da-rollup-bench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_config_parser = subparsers.add_parser("validate-config")
    validate_config_parser.add_argument("path")
    validate_config_parser.add_argument(
        "--kind", choices=("project", "experiment"), default="project"
    )

    workload_parser = subparsers.add_parser("generate-workload")
    workload_parser.add_argument("config")
    workload_parser.add_argument("--output", required=True)

    single_parser = subparsers.add_parser("run-single")
    single_parser.add_argument("config")
    single_parser.add_argument(
        "--strategy", choices=("raw", "compressed", "mock_external"), required=True
    )
    single_parser.add_argument("--output-dir", required=True)

    matrix_parser = subparsers.add_parser("run-matrix")
    matrix_parser.add_argument("experiment")
    matrix_parser.add_argument("--output-root", required=True)
    matrix_parser.add_argument("--preset", choices=("development", "final"))

    summarize_parser = subparsers.add_parser("summarize")
    summarize_parser.add_argument("experiment_directory")

    validate_artifacts_parser = subparsers.add_parser("validate-artifacts")
    validate_artifacts_parser.add_argument("directory")

    args = parser.parse_args(argv)
    if args.command == "validate-config":
        if args.kind == "project":
            config = load_config(args.path)
            _print({"valid": True, "kind": "project", "fingerprint": config.fingerprint()})
        else:
            loaded = load_experiment(args.path)
            _print(
                {
                    "valid": True,
                    "kind": "experiment",
                    "experiment_id": loaded.spec.experiment_id,
                    "scenarios": len(expand_scenarios(loaded)),
                }
            )
        return 0

    if args.command == "generate-workload":
        config = load_config(args.config)
        transactions = generate_workload(config.workload)
        output = Path(args.output).resolve()
        document = workload_document(transactions)
        write_json(output, document)
        _print(
            {
                "output": str(output),
                "transactions": len(transactions),
                "workload_fingerprint": workload_fingerprint(transactions),
                "canonical_hash": canonical_hash(document),
            }
        )
        return 0

    if args.command == "run-single":
        config = load_config(args.config)
        transactions = generate_workload(config.workload)
        strategy = _strategy(args.strategy, config)
        directory = Path(args.output_dir).resolve()
        identity = {
            "mode": "single",
            "strategy_id": strategy.strategy_id,
            "config_fingerprint": config.fingerprint(),
            "workload_fingerprint": workload_fingerprint(transactions),
            "seed": config.workload.seed,
        }
        if (directory / "manifest.json").exists():
            manifest = validate_artifact_directory(directory, identity)
            _print(
                {
                    "resumed": True,
                    "output_directory": str(directory),
                    "result_canonical_hash": manifest["result_canonical_hash"],
                }
            )
            return 0
        result = SimulationEngine(
            batching=config.batching,
            strategy=strategy,
            ethereum=config.ethereum,
            external_da=config.external_da,
            simulation=config.simulation,
        ).run(transactions)
        validation = validate_result(
            result,
            transactions,
            ethereum=config.ethereum,
            external_da=config.external_da,
        )
        if not validation.valid:
            raise RuntimeError("simulation validation failed")
        manifest = persist_run_artifacts(
            directory,
            identity=identity,
            config=config,
            transactions=transactions,
            result=result,
            summary=summarize(result),
            validation=validation,
            repository=Path.cwd(),
        )
        _print(
            {
                "resumed": False,
                "output_directory": str(directory),
                "result_canonical_hash": manifest["result_canonical_hash"],
            }
        )
        return 0

    if args.command == "run-matrix":
        outcome = run_experiment(
            args.experiment, args.output_root, preset_override=args.preset
        )
        _print(
            {
                "output_directory": str(outcome.output_directory),
                "experiment_fingerprint": outcome.experiment_fingerprint,
                "runs": len(outcome.run_records),
                "executed_runs": outcome.executed_runs,
                "resumed_runs": outcome.resumed_runs,
            }
        )
        return 0

    if args.command == "summarize":
        count = resummarize_experiment(args.experiment_directory)
        _print({"summarized_runs": count, "directory": str(Path(args.experiment_directory).resolve())})
        return 0

    directory = Path(args.directory).resolve()
    if (directory / "experiment_manifest.json").exists():
        count = validate_experiment_artifacts(directory)
        _print({"valid": True, "kind": "experiment", "runs": count})
    else:
        manifest = validate_artifact_directory(directory)
        _print(
            {
                "valid": True,
                "kind": "run",
                "result_canonical_hash": manifest["result_canonical_hash"],
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
