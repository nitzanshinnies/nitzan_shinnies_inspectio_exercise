"""No-op outcomes ports for tests and high-throughput runs."""

from __future__ import annotations

from typing import Any


class NullOutcomesReader:
    async def list_failed(self, *, limit: int) -> list[dict[str, Any]]:
        return []

    async def list_success(self, *, limit: int) -> list[dict[str, Any]]:
        return []


class NullOutcomesWriter:
    async def record_failed(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
        reason: str,
    ) -> None:
        return None

    async def record_success(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
    ) -> None:
        return None
