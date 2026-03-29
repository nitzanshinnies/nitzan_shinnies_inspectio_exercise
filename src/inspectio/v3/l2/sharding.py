"""Predicted send shard for admission responses (plans/v3_phases/P1 OpenAPI notes)."""

from __future__ import annotations

from inspectio.v3.domain.shard_index import stable_shard_index


def predicted_shard_index(*, batch_correlation_id: str, shard_count: int) -> int:
    return stable_shard_index(key=batch_correlation_id, shard_count=shard_count)
