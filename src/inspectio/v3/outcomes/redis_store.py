"""Redis-backed outcome rings (LPUSH + LTRIM 100) for L2 GET and worker terminals."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis


class RedisOutcomesStore:
    """Shared store for multiple L2 replicas (§4.8). JSON blobs, newest-first via LPUSH."""

    _CAP = 99  # LTRIM 0 99 → 100 items

    def __init__(self, client: redis.Redis) -> None:
        self._r = client
        self._success_key = "inspectio:v3:outcomes:success"
        self._failed_key = "inspectio:v3:outcomes:failed"

    @classmethod
    def from_url(cls, url: str) -> RedisOutcomesStore:
        return cls(redis.from_url(url, decode_responses=True))

    async def record_success(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
    ) -> None:
        payload = json.dumps(
            {
                "messageId": message_id,
                "attemptCount": attempt_count,
                "finalTimestamp": final_timestamp_ms,
                "reason": None,
            },
        )
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.lpush(self._success_key, payload)
            pipe.ltrim(self._success_key, 0, self._CAP)
            await pipe.execute()

    async def record_failed(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
        reason: str,
    ) -> None:
        payload = json.dumps(
            {
                "messageId": message_id,
                "attemptCount": attempt_count,
                "finalTimestamp": final_timestamp_ms,
                "reason": reason,
            },
        )
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.lpush(self._failed_key, payload)
            pipe.ltrim(self._failed_key, 0, self._CAP)
            await pipe.execute()

    async def list_success(self, *, limit: int) -> list[dict[str, Any]]:
        end = max(0, min(limit, 100) - 1)
        raw = await self._r.lrange(self._success_key, 0, end)
        return [json.loads(x) for x in raw]

    async def list_failed(self, *, limit: int) -> list[dict[str, Any]]:
        end = max(0, min(limit, 100) - 1)
        raw = await self._r.lrange(self._failed_key, 0, end)
        return [json.loads(x) for x in raw]

    async def aclose(self) -> None:
        await self._r.aclose()
