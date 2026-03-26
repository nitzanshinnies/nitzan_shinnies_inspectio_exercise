"""Redis outcomes store for notification service (§5.2, P7)."""

from __future__ import annotations

import json
from typing import Any, Protocol

OUTCOMES_SUCCESS_KEY = "inspectio:outcomes:success"
OUTCOMES_FAILED_KEY = "inspectio:outcomes:failed"


def terminal_key_for_status(status: str) -> str:
    if status == "success":
        return OUTCOMES_SUCCESS_KEY
    return OUTCOMES_FAILED_KEY


class RedisListClient(Protocol):
    async def lpush(self, key: str, value: str) -> int: ...
    async def ltrim(self, key: str, start: int, end: int) -> bool: ...
    async def lrange(self, key: str, start: int, end: int) -> list[str]: ...


class RedisOutcomesStore:
    def __init__(self, *, redis_client: RedisListClient, max_items: int) -> None:
        self._redis = redis_client
        self._max_items = max_items

    async def add_terminal(self, payload: dict[str, Any]) -> None:
        status = str(payload["terminalStatus"])
        key = terminal_key_for_status(status)
        item = {
            "messageId": payload["messageId"],
            "attemptCount": int(payload["attemptCount"]),
            "finalTimestamp": int(payload["finalTimestampMs"]),
            "reason": payload.get("reason"),
        }
        await self._redis.lpush(
            key, json.dumps(item, separators=(",", ":"), sort_keys=True)
        )
        await self._redis.ltrim(key, 0, self._max_items - 1)

    async def get_success(self, *, limit: int) -> list[dict[str, Any]]:
        return await self._read_items(OUTCOMES_SUCCESS_KEY, limit=limit)

    async def get_failed(self, *, limit: int) -> list[dict[str, Any]]:
        return await self._read_items(OUTCOMES_FAILED_KEY, limit=limit)

    async def _read_items(self, key: str, *, limit: int) -> list[dict[str, Any]]:
        raw = await self._redis.lrange(key, 0, limit - 1)
        return [json.loads(item) for item in raw]
