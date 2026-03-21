"""Persistence boundary used by the worker (HTTP client or test fakes)."""

from __future__ import annotations

from typing import Any, Protocol


class PersistenceAsyncPort(Protocol):
    async def delete_object(self, key: str) -> None: ...

    async def get_object(self, key: str) -> bytes: ...

    async def list_prefix(
        self, prefix: str, max_keys: int | None = None
    ) -> list[dict[str, Any]]: ...

    async def put_object(self, key: str, body: bytes, content_type: str = ...) -> None: ...
