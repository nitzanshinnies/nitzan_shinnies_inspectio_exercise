"""Read-through Redis staging for pending bodies before S3 flush (stream ingest mode)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from redis.asyncio import Redis

from inspectio_exercise.common.pending_stream_constants import PENDING_STAGE_KEY_PREFIX
from inspectio_exercise.persistence.object_write import ObjectWrite
from inspectio_exercise.worker.persistence_port import PersistenceAsyncPort


class StagingPersistence:
    """Try Redis staging key first, then delegate (S3 via HTTP)."""

    def __init__(self, redis: Redis, inner: PersistenceAsyncPort) -> None:
        self._inner = inner
        self._redis = redis

    def _stage_key(self, key: str) -> str:
        return f"{PENDING_STAGE_KEY_PREFIX}{key}"

    async def _list_staged_prefix(self, prefix: str) -> list[dict[str, Any]]:
        stage_prefix = self._stage_key(prefix)
        keys: list[str] = []
        async for raw_key in self._redis.scan_iter(match=f"{stage_prefix}*"):
            stage_key = raw_key if isinstance(raw_key, str) else raw_key.decode("utf-8")
            keys.append(stage_key[len(PENDING_STAGE_KEY_PREFIX) :])
        keys.sort()
        return [{"Key": key} for key in keys]

    async def delete_object(self, key: str) -> None:
        await self._redis.delete(self._stage_key(key))
        await self._inner.delete_object(key)

    async def get_object(self, key: str) -> bytes:
        raw = await self._redis.get(self._stage_key(key))
        if raw is not None:
            return raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
        return await self._inner.get_object(key)

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        inner_rows = await self._inner.list_prefix(prefix, None)
        staged_rows = await self._list_staged_prefix(prefix)
        by_key: dict[str, dict[str, Any]] = {}
        for row in inner_rows:
            key = row.get("Key")
            if isinstance(key, str):
                by_key[key] = row
        for row in staged_rows:
            key = row.get("Key")
            if isinstance(key, str):
                by_key[key] = row
        merged = [by_key[key] for key in sorted(by_key)]
        if max_keys is not None:
            return merged[:max_keys]
        return merged

    async def put_object(
        self, key: str, body: bytes, content_type: str = "application/json"
    ) -> None:
        await self._redis.delete(self._stage_key(key))
        await self._inner.put_object(key, body, content_type=content_type)

    async def put_objects(self, items: Sequence[ObjectWrite]) -> None:
        materialized = list(items)
        if not materialized:
            return
        if len(materialized) == 1:
            await self._redis.delete(self._stage_key(materialized[0].key))
        else:
            await self._redis.delete(*[self._stage_key(ow.key) for ow in materialized])
        await self._inner.put_objects(materialized)
