"""Stable shard index from string key (L2 admission hint + expander routing)."""

from __future__ import annotations

import hashlib


def stable_shard_index(*, key: str, shard_count: int) -> int:
    """``sha256(key)[:8] % K`` with ``K >= 1`` (master plan §4.3)."""
    k = shard_count if shard_count >= 1 else 1
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % k
