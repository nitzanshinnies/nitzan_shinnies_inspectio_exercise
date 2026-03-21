"""Test doubles for persistence and other boundaries."""

from __future__ import annotations

from typing import Any


class RecordingPersistence:
    """Async fake implementing `PersistencePort` for spying on call patterns."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.gotten: list[str] = []
        self.listed: list[str] = []
        self.puts: list[tuple[str, bytes]] = []
        self._objects: dict[str, bytes] = {}

    async def delete_object(self, key: str) -> None:
        self.deleted.append(key)
        self._objects.pop(key, None)

    async def get_object(self, key: str) -> bytes:
        self.gotten.append(key)
        if key not in self._objects:
            raise KeyError(key)
        return self._objects[key]

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        self.listed.append(prefix)
        if max_keys is not None and max_keys < 1:
            raise ValueError("max_keys must be >= 1 when set")
        keys = sorted(k for k in self._objects if k.startswith(prefix))
        if max_keys is not None:
            keys = keys[:max_keys]
        return [{"Key": k} for k in keys]

    async def put_object(
        self, key: str, body: bytes, content_type: str = "application/json"
    ) -> None:
        self.puts.append((key, body))
        self._objects[key] = body
