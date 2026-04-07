"""Stable routing from messageId to shard_id and worker shard ownership."""

from __future__ import annotations

import re
import zlib

from inspectio.v3.domain.shard_index import stable_shard_index
from inspectio.v3.iter4_dynamo_wal.constants import (
    DEFAULT_TOTAL_SHARDS,
    DEFAULT_TOTAL_WORKERS,
)


def message_shard_id(
    message_id: str, *, total_shards: int = DEFAULT_TOTAL_SHARDS
) -> str:
    """Partition key for SchedulingIndex (``shard-NN``).

    Uses the same ``sha256(key)[:8] % K`` policy as v3 L2 (master plan §4.3):
    ``hash(message_id) % total_shards``.
    """
    if total_shards < 1:
        raise ValueError("total_shards must be >= 1")
    idx = stable_shard_index(key=message_id, shard_count=total_shards)
    return f"shard-{idx:02d}"


def worker_index_from_hostname(hostname: str) -> int:
    """Parse StatefulSet pod name suffix (``...-0``) or fall back to hashed index."""
    match = re.search(r"-(\d+)$", hostname.strip())
    if match:
        return int(match.group(1))
    fallback = zlib.crc32(hostname.encode("utf-8")) & 0xFFFFFFFF
    return fallback % max(DEFAULT_TOTAL_WORKERS, 1)


def shards_owned_by_worker(
    worker_index: int,
    *,
    total_workers: int,
    total_shards: int,
) -> list[str]:
    """Deterministic shard assignment: shard S belongs to worker ``S % total_workers``."""
    if total_workers < 1 or total_shards < 1:
        raise ValueError("total_workers and total_shards must be >= 1")
    if worker_index < 0 or worker_index >= total_workers:
        raise ValueError("worker_index out of range")
    return [
        f"shard-{s:02d}"
        for s in range(total_shards)
        if s % total_workers == worker_index
    ]
