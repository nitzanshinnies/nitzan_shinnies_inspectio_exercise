"""Publish + hydration logic (Redis + persistence)."""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from inspectio_exercise.notification import config
from inspectio_exercise.notification.keys import notification_object_key
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient


async def hydrate_from_persistence(redis: Redis, persistence: PersistenceHttpClient) -> int:
    """Load up to ``HYDRATION_MAX`` newest notification records from persistence into Redis."""
    rows = await persistence.list_prefix("state/notifications/", max_keys=None)
    records: list[dict[str, Any]] = []
    for row in rows:
        key = row["Key"]
        try:
            raw = await persistence.get_object(key)
        except KeyError:
            continue
        data = json.loads(raw.decode("utf-8"))
        records.append(data)
    records.sort(key=lambda r: int(r["recordedAt"]), reverse=True)
    top = records[: config.HYDRATION_MAX]
    await redis.delete(config.REDIS_KEY_SUCCESS, config.REDIS_KEY_FAILED)
    success = sorted(
        (r for r in top if r.get("outcome") == "success"),
        key=lambda r: int(r["recordedAt"]),
        reverse=True,
    )
    failed = sorted(
        (r for r in top if r.get("outcome") == "failed"),
        key=lambda r: int(r["recordedAt"]),
        reverse=True,
    )
    for r in success:
        await redis.lpush(config.REDIS_KEY_SUCCESS, json.dumps(r, separators=(",", ":")))
    await redis.ltrim(config.REDIS_KEY_SUCCESS, 0, config.OUTCOMES_STREAM_MAX - 1)
    for r in failed:
        await redis.lpush(config.REDIS_KEY_FAILED, json.dumps(r, separators=(",", ":")))
    await redis.ltrim(config.REDIS_KEY_FAILED, 0, config.OUTCOMES_STREAM_MAX - 1)
    return len(top)


async def publish_outcome(redis: Redis, persistence: PersistenceHttpClient, record: dict[str, Any]) -> None:
    """Persist notification JSON to S3, then LPUSH + LTRIM the appropriate Redis stream."""
    notification_id = str(record["notificationId"])
    recorded_at = int(record["recordedAt"])
    key = notification_object_key(notification_id, recorded_at)
    body = json.dumps(record, separators=(",", ":")).encode("utf-8")
    await persistence.put_object(key, body, content_type="application/json")
    stream = config.REDIS_KEY_SUCCESS if record["outcome"] == "success" else config.REDIS_KEY_FAILED
    await redis.lpush(stream, json.dumps(record, separators=(",", ":")))
    await redis.ltrim(stream, 0, config.OUTCOMES_STREAM_MAX - 1)
