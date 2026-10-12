"""Deterministic synthetic workload generation."""

from __future__ import annotations

import hashlib
import math
import random
import struct
from collections.abc import Iterable

from .config import ArrivalProcess, ContentModel, SizeDistribution, WorkloadConfig
from .domain import Transaction


def _derived_rng(seed: int, stream_name: str) -> random.Random:
    """Create stable independent streams without depending on draw ordering."""

    material = f"sc6019:{seed}:{stream_name}".encode("utf-8")
    derived_seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
    return random.Random(derived_seed)


def _arrival_times(config: WorkloadConfig, rng: random.Random) -> Iterable[float]:
    count = 0
    if config.arrival_process == ArrivalProcess.FIXED:
        spacing = 1.0 / config.arrival_rate_tps
        timestamp = 0.0
        while timestamp < config.duration_seconds:
            if config.max_transactions is not None and count >= config.max_transactions:
                return
            yield timestamp
            count += 1
            timestamp = count * spacing
        return

    timestamp = 0.0
    while True:
        timestamp += rng.expovariate(config.arrival_rate_tps)
        if timestamp >= config.duration_seconds:
            return
        if config.max_transactions is not None and count >= config.max_transactions:
            return
        yield timestamp
        count += 1


def _transaction_size(config: WorkloadConfig, rng: random.Random) -> int:
    if config.size_distribution == SizeDistribution.FIXED:
        return config.fixed_size_bytes
    return rng.choices(
        config.categorical_sizes_bytes,
        weights=config.categorical_weights,
        k=1,
    )[0]


def _payload(config: WorkloadConfig, rng: random.Random, size: int) -> bytes:
    if config.content_model == ContentModel.HIGH_ENTROPY:
        return rng.randbytes(size)
    if config.content_model == ContentModel.ZERO_FRACTION:
        output = bytearray(size)
        for index in range(size):
            if rng.random() >= config.zero_probability:
                output[index] = rng.randrange(1, 256)
        return bytes(output)
    pattern = bytes.fromhex(config.repeated_pattern_hex)
    repeats = math.ceil(size / len(pattern))
    return (pattern * repeats)[:size]


def generate_workload(config: WorkloadConfig) -> tuple[Transaction, ...]:
    """Generate the same transactions for the same validated config and seed."""

    arrival_rng = _derived_rng(config.seed, "arrivals")
    size_rng = _derived_rng(config.seed, "sizes")
    payload_rng = _derived_rng(config.seed, "payloads")
    transactions = []
    for index, arrival_time in enumerate(_arrival_times(config, arrival_rng)):
        size = _transaction_size(config, size_rng)
        transactions.append(
            Transaction(
                tx_id=f"tx-{index:08d}",
                arrival_time=arrival_time,
                payload=_payload(config, payload_rng, size),
            )
        )
    return tuple(transactions)


def workload_fingerprint(transactions: Iterable[Transaction]) -> str:
    """Hash canonical binary transaction records for cross-strategy pairing."""

    digest = hashlib.sha256()
    for transaction in transactions:
        tx_id = transaction.tx_id.encode("utf-8")
        digest.update(struct.pack(">I", len(tx_id)))
        digest.update(tx_id)
        digest.update(struct.pack(">dQ", transaction.arrival_time, len(transaction.payload)))
        digest.update(transaction.payload)
    return digest.hexdigest()
