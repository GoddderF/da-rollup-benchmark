"""Canonical, versioned, atomic artifact serialization and validation."""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import os
import platform
import subprocess
import sys
import zlib
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from .config import ProjectConfig
from .domain import Transaction
from .engine import SimulationResult
from .metrics import MetricsSummary, ValidationReport

ARTIFACT_SCHEMA_VERSION = 1


def to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"encoding": "hex", "data": value.hex()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        to_jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, canonical_json(value) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def runtime_versions(repository: Path | None = None) -> dict[str, Any]:
    revision = None
    if repository is not None and (repository / ".git").exists():
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository,
                capture_output=True,
                check=True,
                text=True,
                timeout=5,
            )
            revision = completed.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            revision = None
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "code_revision": revision,
    }


def workload_document(transactions: tuple[Transaction, ...]) -> dict[str, Any]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "transactions": [
            {
                "tx_id": transaction.tx_id,
                "arrival_time": transaction.arrival_time,
                "payload_hex": transaction.payload.hex(),
            }
            for transaction in transactions
        ],
    }


def workload_from_document(document: dict[str, Any]) -> tuple[Transaction, ...]:
    if document.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported workload artifact schema")
    return tuple(
        Transaction(
            tx_id=item["tx_id"],
            arrival_time=item["arrival_time"],
            payload=bytes.fromhex(item["payload_hex"]),
        )
        for item in document["transactions"]
    )


def _transaction_rows(result: SimulationResult) -> list[dict[str, Any]]:
    return [
        {
            "tx_id": item.tx_id,
            "state": item.state.value,
            "arrival_time_seconds": item.arrival_time,
            "batch_id": item.batch_id,
            "completion_time_seconds": item.completion_time,
            "rejection_reason": item.rejection_reason,
            "batching_latency_seconds": item.batching_latency,
            "queue_latency_seconds": item.queue_latency,
            "service_latency_seconds": item.service_latency,
            "retry_backoff_seconds": item.retry_backoff_latency,
            "confirmation_latency_seconds": item.confirmation_latency,
            "end_to_end_latency_seconds": item.end_to_end_latency,
        }
        for item in result.transactions
    ]


def _publication_rows(result: SimulationResult) -> list[dict[str, Any]]:
    rows = []
    for publication in result.publications:
        rows.append(
            {
                "publication_id": publication.publication_id,
                "batch_id": publication.batch_id,
                "state": publication.state.value,
                "raw_payload_bytes": publication.prepared.raw_payload_bytes,
                "encoded_bytes": publication.prepared.encoded_bytes,
                "capacity_demand": publication.prepared.capacity_demand,
                "capacity_unit": publication.prepared.capacity_unit,
                "attempts": len(publication.attempts),
                "total_cost": str(publication.total_cost),
                "cost_unit": publication.prepared.monetary_cost_unit,
                "retry_backoff_seconds": publication.retry_backoff_seconds,
                "confirmation_time_seconds": publication.confirmation_time,
                "rejection_reason": publication.rejection_reason,
            }
        )
    return rows


def persist_run_artifacts(
    directory: Path,
    *,
    identity: dict[str, Any],
    config: ProjectConfig,
    transactions: tuple[Transaction, ...],
    result: SimulationResult,
    summary: MetricsSummary,
    validation: ValidationReport,
    repository: Path | None = None,
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()) and not (directory / "manifest.json").exists():
        raise ValueError(f"refusing to overwrite incomplete artifact directory: {directory}")

    files: dict[str, Any] = {
        "config.json": to_jsonable(config.model_dump(mode="json")),
        "workload.json": workload_document(transactions),
        "result.json": {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "simulation_result": to_jsonable(result),
        },
        "summary.json": {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "summary": to_jsonable(summary),
        },
        "validation.json": {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "validation": to_jsonable(validation),
        },
    }
    for name, document in files.items():
        write_json(directory / name, document)

    transaction_rows = _transaction_rows(result)
    publication_rows = _publication_rows(result)
    write_csv(
        directory / "transactions.csv",
        transaction_rows,
        list(transaction_rows[0]) if transaction_rows else ["tx_id"],
    )
    write_csv(
        directory / "publications.csv",
        publication_rows,
        list(publication_rows[0]) if publication_rows else ["publication_id"],
    )
    artifact_names = list(files) + ["transactions.csv", "publications.csv"]
    hashes = {name: sha256_file(directory / name) for name in artifact_names}
    manifest = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "identity": identity,
        "runtime": runtime_versions(repository),
        "result_canonical_hash": canonical_hash(result),
        "batch_signature_hash": canonical_hash(
            [
                {
                    "batch_id": batch.batch_id,
                    "transaction_ids": [tx.tx_id for tx in batch.transactions],
                    "raw_payload": batch.raw_payload,
                }
                for batch in result.batches
            ]
        ),
        "artifacts": hashes,
    }
    write_json(directory / "manifest.json", manifest)
    return manifest


def validate_artifact_directory(
    directory: Path, expected_identity: dict[str, Any] | None = None
) -> dict[str, Any]:
    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"missing manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("unsupported artifact schema")
    if expected_identity is not None and manifest.get("identity") != expected_identity:
        raise ValueError("artifact identity is incompatible with requested run")
    for name, expected_hash in manifest.get("artifacts", {}).items():
        path = directory / name
        if not path.exists() or sha256_file(path) != expected_hash:
            raise ValueError(f"artifact hash mismatch: {name}")
    validation = json.loads((directory / "validation.json").read_text(encoding="utf-8"))
    if not all(validation["validation"].values()):
        raise ValueError("stored simulation invariants did not pass")
    return manifest

