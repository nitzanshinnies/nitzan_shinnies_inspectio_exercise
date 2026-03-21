"""Deterministic shard assignment — matches `tests/reference_spec.py` + plans/SHARDING.md."""

from __future__ import annotations

import hashlib
import re


def is_shard_owned(
    shard_id: int,
    pod_index: int,
    shards_per_pod: int,
    total_shards: int,
) -> bool:
    return shard_id in owned_shard_ids(pod_index, shards_per_pod, total_shards)


def owned_shard_ids(pod_index: int, shards_per_pod: int, total_shards: int) -> frozenset[int]:
    if total_shards < 0 or shards_per_pod < 0:
        raise ValueError("total_shards and shards_per_pod must be non-negative")
    if total_shards == 0:
        return frozenset()
    start = pod_index * shards_per_pod
    if start >= total_shards:
        return frozenset()
    end = min((pod_index + 1) * shards_per_pod, total_shards)
    return frozenset(range(start, end))


def pending_prefix_for_shard(shard_id: int) -> str:
    return f"state/pending/shard-{shard_id}/"


def pod_index_from_hostname(hostname: str) -> int:
    m = re.search(r"(?:^|-)(\d+)$", hostname.strip())
    if not m:
        raise ValueError(f"cannot derive pod index from hostname: {hostname!r}")
    return int(m.group(1))


def shard_id_for_message(message_id: str, total_shards: int) -> int:
    if total_shards <= 0:
        raise ValueError("total_shards must be positive")
    digest = hashlib.sha256(message_id.encode("utf-8")).digest()
    value = int.from_bytes(digest, "big")
    return value % total_shards
