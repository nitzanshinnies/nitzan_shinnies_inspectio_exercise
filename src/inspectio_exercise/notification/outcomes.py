"""Publish + hydration logic (hot store + persistence)."""

from __future__ import annotations

import json
from typing import Any

from inspectio_exercise.notification import config
from inspectio_exercise.notification.keys import notification_object_key
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.notification.store.interface import OutcomesHotStore


async def hydrate_from_persistence(
    store: OutcomesHotStore, persistence: PersistenceHttpClient
) -> int:
    """Load up to ``HYDRATION_MAX`` newest notification records from persistence into the store."""
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
    await store.clear_all_streams()
    # LPUSH builds head-to-tail: push *oldest* first so the list reads
    # [newest, …, oldest] and LRANGE 0 N-1 matches NOTIFICATION_SERVICE.md §6 (newest first).
    success = sorted(
        (r for r in top if r.get("outcome") == "success"),
        key=lambda r: int(r["recordedAt"]),
        reverse=False,
    )
    failed = sorted(
        (r for r in top if r.get("outcome") == "failed"),
        key=lambda r: int(r["recordedAt"]),
        reverse=False,
    )
    for r in success:
        await store.prepend_to_success_stream(json.dumps(r, separators=(",", ":")))
    await store.trim_success_stream()
    for r in failed:
        await store.prepend_to_failed_stream(json.dumps(r, separators=(",", ":")))
    await store.trim_failed_stream()
    return len(top)


async def publish_outcome(
    store: OutcomesHotStore, persistence: PersistenceHttpClient, record: dict[str, Any]
) -> None:
    """Persist notification JSON to S3, then update the appropriate hot stream."""
    notification_id = str(record["notificationId"])
    recorded_at = int(record["recordedAt"])
    key = notification_object_key(notification_id, recorded_at)
    body = json.dumps(record, separators=(",", ":")).encode("utf-8")
    await persistence.put_object(key, body, content_type="application/json")
    payload = json.dumps(record, separators=(",", ":"))
    if record["outcome"] == "success":
        await store.prepend_to_success_stream(payload)
        await store.trim_success_stream()
    else:
        await store.prepend_to_failed_stream(payload)
        await store.trim_failed_stream()
