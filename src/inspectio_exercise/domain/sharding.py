"""Deterministic shard assignment and worker ownership (plans/SHARDING.md, PLAN.md §4)."""

from __future__ import annotations

import hashlib
import re


def is_shard_owned(
    shard_id: int,
    pod_index: int,
    shards_per_pod: int,
    total_shards: int,
) -> bool:
    """Whether `shard_id` is in this pod's half-open range."""
    return shard_id in owned_shard_ids(pod_index, shards_per_pod, total_shards)


def owned_shard_ids(pod_index: int, shards_per_pod: int, total_shards: int) -> frozenset[int]:
    """`range(pod_index * shards_per_pod, min((pod_index + 1) * shards_per_pod, total_shards))`."""
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
    """S3 prefix for pending objects for this shard."""
    return f"state/pending/shard-{shard_id}/"


def pod_index_from_hostname(hostname: str) -> int:
    """Parse StatefulSet ordinal from hostnames like `worker-0`, `sms-worker-2`."""
    m = re.search(r"(?:^|-)(\d+)$", hostname.strip())
    if not m:
        raise ValueError(f"cannot derive pod index from hostname: {hostname!r}")
    return int(m.group(1))


def shard_id_for_message(message_id: str, total_shards: int) -> int:
    """`sha256(messageId) % TOTAL_SHARDS` using the first 8 bytes as unsigned int."""
    if total_shards <= 0:
        raise ValueError("total_shards must be positive")
    digest = hashlib.sha256(message_id.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big")
    return value % total_shards
