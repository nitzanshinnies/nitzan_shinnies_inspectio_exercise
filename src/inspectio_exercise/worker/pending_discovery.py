"""List owned shard prefixes and ingest new pending objects into the due queue."""

from __future__ import annotations

import logging

from inspectio_exercise.domain.sharding import pending_prefix_for_shard
from inspectio_exercise.worker.due_work_queue import DueWorkQueue
from inspectio_exercise.worker.pending_record import message_id_from_pending_key
from inspectio_exercise.worker.retrying_persistence import RetryingPersistence

logger = logging.getLogger(__name__)


async def discover_owned_pending(
    owned_shards: frozenset[int],
    persist: RetryingPersistence,
    queue: DueWorkQueue,
) -> None:
    for shard in owned_shards:
        prefix = pending_prefix_for_shard(shard)
        try:
            rows = await persist.list_prefix(prefix)
        except Exception:
            logger.exception("list_prefix failed prefix=%s after retries", prefix)
            continue
        for row in rows:
            key = row["Key"]
            mid = message_id_from_pending_key(key)
            if mid is None:
                continue
            async with queue.lock:
                known = mid in queue.records
            if known:
                continue
            try:
                raw = await persist.get_object(key)
            except KeyError:
                continue
            except Exception:
                logger.exception("get_object failed key=%s after retries", key)
                continue
            await queue.ingest_if_new(mid, key, raw)
