from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from inspectio_exercise.persistence.object_write import ObjectWrite


@runtime_checkable
class PersistencePort(Protocol):
    """Contract for API/worker code — implement with HTTP client or in-proc adapter."""

    async def delete_object(self, key: str) -> None: ...

    async def get_object(self, key: str) -> bytes: ...

    async def list_prefix(
        self, prefix: str, max_keys: int | None = None
    ) -> list[dict[str, Any]]: ...

    async def put_object(
        self, key: str, body: bytes, content_type: str = "application/json"
    ) -> None: ...

    async def put_objects(self, items: Sequence[ObjectWrite]) -> None: ...
