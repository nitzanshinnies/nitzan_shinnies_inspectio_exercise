"""Publish terminal outcomes to the notification service with retries."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx

from inspectio_exercise.worker.config import (
    NOTIFICATION_PUBLISH_BASE_DELAY_SEC,
    NOTIFICATION_PUBLISH_MAX_ATTEMPTS,
    OUTCOMES_HTTP_PATH,
)

logger = logging.getLogger(__name__)


class OutcomeNotifier:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def publish(
        self,
        *,
        message_id: str,
        outcome: str,
        recorded_at: int,
        shard_id: int,
        attempt_count: int | None = None,
        brief_reason: str | None = None,
        terminal_storage_key: str | None = None,
    ) -> None:
        if terminal_storage_key is not None:
            notification_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{terminal_storage_key}\n{outcome}")
            )
        else:
            notification_id = str(uuid.uuid4())
        body: dict[str, Any] = {
            "messageId": message_id,
            "notificationId": notification_id,
            "outcome": outcome,
            "recordedAt": recorded_at,
            "finalTimestamp": recorded_at,
            "shardId": shard_id,
        }
        if attempt_count is not None:
            body["attemptCount"] = attempt_count
        if brief_reason is not None:
            body["reason"] = brief_reason
        last_exc: httpx.HTTPError | None = None
        for try_idx in range(NOTIFICATION_PUBLISH_MAX_ATTEMPTS):
            try:
                response = await self._client.post(OUTCOMES_HTTP_PATH, json=body)
                response.raise_for_status()
                return
            except httpx.HTTPError as exc:
                last_exc = exc
                if try_idx + 1 >= NOTIFICATION_PUBLISH_MAX_ATTEMPTS:
                    break
                delay = NOTIFICATION_PUBLISH_BASE_DELAY_SEC * (2**try_idx)
                await asyncio.sleep(delay)
        assert last_exc is not None
        logger.error(
            "notification publish exhausted attempts message_id=%s",
            message_id,
            exc_info=last_exc,
        )
        raise last_exc
