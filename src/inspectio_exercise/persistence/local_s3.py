"""File-backed ``PersistencePort`` for local dev and tests.

Spec: ``plans/LOCAL_S3.md``. Blocking filesystem calls run in a thread pool via
``asyncio.to_thread`` so the public API stays async without extra dependencies.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from inspectio_exercise.persistence import config
from inspectio_exercise.persistence.key_policy import (
    validate_list_prefix,
    validate_max_keys,
    validate_object_key,
)
from inspectio_exercise.persistence.object_write import ObjectWrite


class LocalS3Provider:
    """``PersistencePort`` implementation backed by ``root / <s3-key>`` on disk."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).expanduser().resolve()

    def _object_path(self, key: str) -> Path:
        validate_object_key(key)
        return self._root / key

    def _put_sync(self, path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def _put_many_sync(self, pairs: list[tuple[Path, bytes]]) -> None:
        if not pairs:
            return
        workers = min(len(pairs), config.PERSISTENCE_PUT_MAX_WORKERS)
        if workers <= 1:
            for path, body in pairs:
                self._put_sync(path, body)
            return
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._put_sync, path, body) for path, body in pairs]
            for fut in as_completed(futures):
                fut.result()

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
        validate_list_prefix(prefix)
        validate_max_keys(max_keys)
        return await asyncio.to_thread(self._list_prefix_sync, prefix, max_keys)

    async def put_object(
        self, key: str, body: bytes, content_type: str = "application/json"
    ) -> None:
        del content_type  # LOCAL_S3.md §3 — bytes only on disk; ignored until sidecar exists
        path = self._object_path(key)
        await asyncio.to_thread(self._put_sync, path, body)

    async def put_objects(self, items: Sequence[ObjectWrite]) -> None:
        materialized = list(items)
        if not materialized:
            return
        pairs: list[tuple[Path, bytes]] = []
        for ow in materialized:
            pairs.append((self._object_path(ow.key), ow.body))
        await asyncio.to_thread(self._put_many_sync, pairs)
