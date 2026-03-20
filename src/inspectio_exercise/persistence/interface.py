from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PersistencePort(Protocol):
    """Contract for API/worker code — implement with HTTP client or in-proc adapter."""

    async def put_object(self, key: str, body: bytes, content_type: str = "application/json") -> None:
        ...

    async def get_object(self, key: str) -> bytes:
        ...

    async def delete_object(self, key: str) -> None:
        ...

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        ...
