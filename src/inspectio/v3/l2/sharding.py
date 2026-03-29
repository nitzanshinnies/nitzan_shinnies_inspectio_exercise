"""Predicted send shard for admission responses (plans/v3_phases/P1 OpenAPI notes)."""

from __future__ import annotations

import hashlib


def predicted_shard_index(*, batch_correlation_id: str, shard_count: int) -> int:
    k = shard_count if shard_count >= 1 else 1
    digest = hashlib.sha256(batch_correlation_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % k
