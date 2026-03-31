"""Object-store abstraction for writer segments/checkpoints (P12.3)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PersistenceObjectStore(Protocol):
    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        content_encoding: str | None = None,
    ) -> None: ...

    async def put_json(self, *, key: str, data: dict[str, Any]) -> None: ...

    async def get_json(self, *, key: str) -> dict[str, Any] | None: ...

    async def get_bytes(self, *, key: str) -> bytes | None: ...

    async def list_keys(self, *, prefix: str) -> list[str]: ...
