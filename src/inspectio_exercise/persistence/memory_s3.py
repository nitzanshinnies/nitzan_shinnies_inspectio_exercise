"""In-process dict ``PersistencePort`` for local dev / fast tests (opt-in via env).

Spec: same key/list semantics as ``plans/LOCAL_S3.md`` §2–§4. Optional
``flush_to_disk`` mirrors the file-backed layout under a root directory.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from inspectio_exercise.persistence.key_policy import (
    validate_list_prefix,
    validate_max_keys,
    validate_object_key,
)
from inspectio_exercise.persistence.object_write import ObjectWrite


class MemoryLocalS3Provider:
    """``PersistencePort`` backed by ``dict[str, bytes]`` (volatile; single process)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._objects: dict[str, bytes] = {}

    async def delete_object(self, key: str) -> None:
        validate_object_key(key)
        async with self._lock:
            self._objects.pop(key, None)

    async def flush_to_disk(self, root: Path | str) -> None:
        """Write every stored object to ``root / <key>`` (same layout as ``LocalS3Provider``).

        Holds the async lock for the whole operation so the on-disk tree matches a single
        consistent snapshot and concurrent mutators wait until flush completes.
        """
        base = Path(root).expanduser().resolve()
        async with self._lock:
            for key, body in list(self._objects.items()):
                validate_object_key(key)
                path = base / key
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)

    async def get_object(self, key: str) -> bytes:
        validate_object_key(key)
        async with self._lock:
            if key not in self._objects:
                raise KeyError(key)
            return self._objects[key]

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        validate_list_prefix(prefix)
        validate_max_keys(max_keys)
        async with self._lock:
            matching = sorted(k for k in self._objects if k.startswith(prefix))
        if max_keys is not None:
            matching = matching[:max_keys]
        return [{"Key": k} for k in matching]

    async def put_object(
        self, key: str, body: bytes, content_type: str = "application/json"
    ) -> None:
        await self.put_objects((ObjectWrite(key=key, body=body, content_type=content_type),))

    async def put_objects(self, items: Sequence[ObjectWrite]) -> None:
        materialized = list(items)
        if not materialized:
            return
        async with self._lock:
            for ow in materialized:
                validate_object_key(ow.key)
                self._objects[ow.key] = ow.body
