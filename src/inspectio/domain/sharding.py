"""Deterministic shard assignment math ."""

from __future__ import annotations

import hashlib
import math

HASH_PREFIX_BYTES = 4
MIN_TOTAL_SHARDS = 1
MIN_WORKER_COUNT = 1


def owned_shard_range(
    pod_index: int,
    total_shards: int,
    worker_count: int,
) -> tuple[int, int]:
    """Return ``[start, end_excl)`` shard ids owned by ``pod_index`` ."""
    validate_total_shards_vs_workers(total_shards, worker_count)
    if pod_index < 0 or pod_index >= worker_count:
        msg = f"pod_index must be in [0, {worker_count})"
        raise ValueError(msg)
    spp = shards_per_pod(total_shards, worker_count)
    start = pod_index * spp
    end_excl = min((pod_index + 1) * spp, total_shards)
    return (start, end_excl)


def shard_for_message(message_id: str, total_shards: int) -> int:
    """Map ``message_id`` to ``shard_id`` using SHA-256 first-4-bytes BE."""
    if total_shards < MIN_TOTAL_SHARDS:
        msg = f"total_shards must be >= {MIN_TOTAL_SHARDS}"
        raise ValueError(msg)

    digest = hashlib.sha256(message_id.encode("utf-8")).digest()
    hash_prefix = digest[:HASH_PREFIX_BYTES]
    hash_value = int.from_bytes(hash_prefix, byteorder="big", signed=False)
    return hash_value % total_shards


def shards_per_pod(total_shards: int, worker_count: int) -> int:
    """``ceil(TOTAL_SHARDS / W)`` per"""
    validate_total_shards_vs_workers(total_shards, worker_count)
    return math.ceil(total_shards / worker_count)


def validate_total_shards_vs_workers(total_shards: int, worker_count: int) -> None:
    """: ``TOTAL_SHARDS >= W``; both must be positive."""
    if total_shards < MIN_TOTAL_SHARDS:
        msg = f"total_shards must be >= {MIN_TOTAL_SHARDS}"
        raise ValueError(msg)
    if worker_count < MIN_WORKER_COUNT:
        msg = f"worker_count must be >= {MIN_WORKER_COUNT}"
        raise ValueError(msg)
    if total_shards < worker_count:
        msg = "total_shards must be >= worker_count "
        raise ValueError(msg)
