"""File-backed ``PersistencePort`` for local dev and tests.

Spec: ``plans/LOCAL_S3.md``. Blocking filesystem calls run in a thread pool via
``asyncio.to_thread`` so the public API stays async without extra dependencies.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


class LocalS3Provider:
    """``PersistencePort`` implementation backed by ``root / <s3-key>`` on disk."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).expanduser().resolve()

    def _validate_object_key(self, key: str) -> None:
        if not key:
            raise ValueError("object key must be non-empty")
        if key.startswith("/"):
            raise ValueError("object key must not start with '/'")
        if any(part == ".." for part in key.split("/")):
            raise ValueError("object key must not contain '..' path segments")

    def _validate_list_prefix(self, prefix: str) -> None:
        if not prefix:
            raise ValueError("list_prefix prefix must be non-empty (see LOCAL_S3.md §4.4)")

    @staticmethod
    def _validate_max_keys(max_keys: int | None) -> None:
        if max_keys is not None and max_keys < 1:
            raise ValueError("max_keys must be >= 1 when set")

    def _object_path(self, key: str) -> Path:
        self._validate_object_key(key)
        return self._root / key

    def _put_sync(self, path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def _get_sync(self, path: Path, key: str) -> bytes:
        if not path.is_file():
            raise KeyError(key)
        return path.read_bytes()

    def _delete_sync(self, path: Path) -> None:
        if path.is_file():
            path.unlink()

    def _list_prefix_sync(self, prefix: str, max_keys: int | None) -> list[dict[str, Any]]:
        if not self._root.is_dir():
            return []
        keys: list[str] = []
        for path in self._root.rglob("*"):
            if path.is_file():
                rel = path.relative_to(self._root)
                keys.append(rel.as_posix())
        matching = [k for k in keys if k.startswith(prefix)]
        matching.sort()
        if max_keys is not None:
            matching = matching[:max_keys]
        return [{"Key": k} for k in matching]

    async def delete_object(self, key: str) -> None:
        path = self._object_path(key)
        await asyncio.to_thread(self._delete_sync, path)

    async def get_object(self, key: str) -> bytes:
        path = self._object_path(key)
        return await asyncio.to_thread(self._get_sync, path, key)

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        self._validate_list_prefix(prefix)
        self._validate_max_keys(max_keys)
        return await asyncio.to_thread(self._list_prefix_sync, prefix, max_keys)

    async def put_object(self, key: str, body: bytes, content_type: str = "application/json") -> None:
        del content_type  # LOCAL_S3.md §3 — bytes only on disk; ignored until sidecar exists
        path = self._object_path(key)
        await asyncio.to_thread(self._put_sync, path, body)
