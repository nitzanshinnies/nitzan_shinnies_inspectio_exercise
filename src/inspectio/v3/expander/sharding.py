"""Route send units by ``messageId`` (plans/v3_phases/P3_EXPANDER.md)."""

from __future__ import annotations

from inspectio.v3.domain.shard_index import stable_shard_index


def shard_for_message_id(message_id: str, shard_count: int) -> int:
    return stable_shard_index(key=message_id, shard_count=shard_count)
