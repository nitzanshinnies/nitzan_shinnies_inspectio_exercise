"""Redis bounded lists for terminal outcomes ."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

KEY_SUCCESS = "inspectio:outcomes:success"
KEY_FAILED = "inspectio:outcomes:failed"
LIST_MAX_LEN = 10_000


class OutcomesStore:
    def __init__(self, client: redis.Redis) -> None:
        self._r = client

    async def record_terminal(self, row: dict[str, Any]) -> None:
        status = row.get("terminalStatus")
        if status == "success":
            key = KEY_SUCCESS
        elif status == "failed":
            key = KEY_FAILED
        else:
            msg = "terminalStatus must be success or failed"
            raise ValueError(msg)
        blob = json.dumps(row, separators=(",", ":"), sort_keys=True)
        await self._r.lpush(key, blob)
        await self._r.ltrim(key, 0, LIST_MAX_LEN - 1)

    async def list_success(self, limit: int) -> list[dict[str, Any]]:
        raw = await self._r.lrange(KEY_SUCCESS, 0, limit - 1)
        return [_decode_json(x) for x in raw]

    async def list_failed(self, limit: int) -> list[dict[str, Any]]:
        raw = await self._r.lrange(KEY_FAILED, 0, limit - 1)
        return [_decode_json(x) for x in raw]


def _decode_json(x: bytes | str) -> dict[str, Any]:
    if isinstance(x, (bytes, bytearray)):
        x = x.decode("utf-8")
    return json.loads(x)
