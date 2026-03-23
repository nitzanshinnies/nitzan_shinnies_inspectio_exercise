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

    async def delete_object(self, key: str) -> None:
        await self._redis.delete(self._stage_key(key))
        await self._inner.delete_object(key)

    async def get_object(self, key: str) -> bytes:
        raw = await self._redis.get(self._stage_key(key))
        if raw is not None:
            return raw if isinstance(raw, bytes) else str(raw).encode("utf-8")
        return await self._inner.get_object(key)

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        return await self._inner.list_prefix(prefix, max_keys)

    async def put_object(
        self, key: str, body: bytes, content_type: str = "application/json"
    ) -> None:
        await self._inner.put_object(key, body, content_type=content_type)

    async def put_objects(self, items: Sequence[ObjectWrite]) -> None:
        await self._inner.put_objects(items)
