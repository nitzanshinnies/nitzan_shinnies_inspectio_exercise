"""Wrap a ``PersistenceAsyncPort`` with bounded retries on transient errors."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from inspectio_exercise.persistence.object_write import ObjectWrite
from inspectio_exercise.worker.persistence_port import PersistenceAsyncPort
from inspectio_exercise.worker.persistence_retry import run_with_persistence_retries


class RetryingPersistence:
    def __init__(
        self,
        inner: PersistenceAsyncPort,
        *,
        base_delay_sec: float,
        max_attempts: int,
    ) -> None:
        self._base_delay_sec = base_delay_sec
        self._inner = inner
        self._max_attempts = max_attempts

    async def delete_object(self, key: str) -> None:
        async def call() -> None:
            await self._inner.delete_object(key)

        await run_with_persistence_retries(
            f"delete_object:{key!r}",
            call,
            max_attempts=self._max_attempts,
            base_delay_sec=self._base_delay_sec,
        )

    async def get_object(self, key: str) -> bytes:
        async def call() -> bytes:
            return await self._inner.get_object(key)

        return await run_with_persistence_retries(
            f"get_object:{key!r}",
            call,
            max_attempts=self._max_attempts,
            base_delay_sec=self._base_delay_sec,
        )

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        async def call() -> list[dict[str, Any]]:
            return await self._inner.list_prefix(prefix, max_keys)

        return await run_with_persistence_retries(
            f"list_prefix:{prefix!r}",
            call,
            max_attempts=self._max_attempts,
            base_delay_sec=self._base_delay_sec,
        )

    async def put_object(
        self, key: str, raw: bytes, content_type: str = "application/json"
    ) -> None:
        async def call() -> None:
            await self._inner.put_object(key, raw, content_type=content_type)

        await run_with_persistence_retries(
            f"put_object:{key!r}",
            call,
            max_attempts=self._max_attempts,
            base_delay_sec=self._base_delay_sec,
        )

    async def put_objects(self, items: Sequence[ObjectWrite]) -> None:
        materialized = list(items)
        if not materialized:
            return

        async def call() -> None:
            await self._inner.put_objects(materialized)

        keys_preview = ",".join(repr(ow.key) for ow in materialized[:3])
        suffix = "..." if len(materialized) > 3 else ""
        await run_with_persistence_retries(
            f"put_objects:[{keys_preview}{suffix}] n={len(materialized)}",
            call,
            max_attempts=self._max_attempts,
            base_delay_sec=self._base_delay_sec,
        )
