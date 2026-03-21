"""Orchestration for message submission — persistence only via PersistenceHttpClient."""

from __future__ import annotations

import json
import time
import uuid

from inspectio_exercise.domain.sharding import pending_prefix_for_shard, shard_id_for_message
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient


def _now_ms() -> int:
    return int(time.time() * 1000)


async def submit_message(
    persistence: PersistenceHttpClient,
    *,
    total_shards: int,
    to: str,
    body: str,
) -> str:
    """Persist a new pending record; return ``messageId`` (UUID string)."""
    message_id = str(uuid.uuid4())
    shard_id = shard_id_for_message(message_id, total_shards)
    key = f"{pending_prefix_for_shard(shard_id)}{message_id}.json"
    now_ms = _now_ms()
    record = {
        "messageId": message_id,
        "attemptCount": 0,
        "nextDueAt": now_ms,
        "status": "pending",
        "payload": {"to": to, "body": body},
        "history": [],
    }
    raw = json.dumps(record, separators=(",", ":")).encode("utf-8")
    await persistence.put_object(key, raw)
    return message_id
