"""Deterministic shard assignment math (§16.2)."""

from __future__ import annotations

import hashlib

HASH_PREFIX_BYTES = 4
MIN_TOTAL_SHARDS = 1


def shard_for_message(message_id: str, total_shards: int) -> int:
    """Map ``message_id`` to ``shard_id`` using SHA-256 first-4-bytes BE."""
    if total_shards < MIN_TOTAL_SHARDS:
        msg = f"total_shards must be >= {MIN_TOTAL_SHARDS}"
        raise ValueError(msg)

    digest = hashlib.sha256(message_id.encode("utf-8")).digest()
    hash_prefix = digest[:HASH_PREFIX_BYTES]
    hash_value = int.from_bytes(hash_prefix, byteorder="big", signed=False)
    return hash_value % total_shards
