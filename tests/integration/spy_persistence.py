"""Test doubles: record persistence calls (plans/TESTS.md §4.5 spy)."""

from __future__ import annotations

from typing import Any

from inspectio_exercise.notification.persistence_client import PersistenceHttpClient


class SpyPersistenceClient:
    """Delegates to a real client and records ``list_prefix`` invocations."""

    def __init__(self, inner: PersistenceHttpClient) -> None:
        self._inner = inner
        self.list_prefix_calls: list[tuple[str, int | None]] = []

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def delete_object(self, key: str) -> None:
        await self._inner.delete_object(key)

    async def get_object(self, key: str) -> bytes:
        return await self._inner.get_object(key)

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        self.list_prefix_calls.append((prefix, max_keys))
        return await self._inner.list_prefix(prefix, max_keys)

    async def put_object(
        self, key: str, body: bytes, content_type: str = "application/json"
    ) -> None:
        await self._inner.put_object(key, body, content_type=content_type)
