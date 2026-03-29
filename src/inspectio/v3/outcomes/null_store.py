"""No-op / empty outcomes reader for tests and L2 without Redis."""

from __future__ import annotations

from typing import Any


class NullOutcomesReader:
    async def list_failed(self, *, limit: int) -> list[dict[str, Any]]:
        return []

    async def list_success(self, *, limit: int) -> list[dict[str, Any]]:
        return []
