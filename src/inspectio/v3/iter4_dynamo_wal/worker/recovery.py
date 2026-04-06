"""Boot-time heap hydration from DynamoDB GSI."""

from __future__ import annotations

import heapq

from inspectio.v3.iter4_dynamo_wal.message_repository import MessageRepository


async def load_heap_from_dynamo(
    *,
    repo: MessageRepository,
    shard_ids: list[str],
    heap: list[tuple[int, str]],
    scheduled_ids: set[str],
) -> int:
    """Load all pending messages for owned shards. Returns rows loaded."""
    loaded = 0
    for shard_id in shard_ids:
        rows = await repo.load_all_pending_for_shard(shard_id)
        for row in rows:
            mid = str(row["messageId"])
            due = int(row["nextDueAt"])
            if mid in scheduled_ids:
                continue
            heapq.heappush(heap, (due, mid))
            scheduled_ids.add(mid)
            loaded += 1
    return loaded
