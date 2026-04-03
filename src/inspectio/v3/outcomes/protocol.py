"""Read/write ports for GET /messages/success|failed (master plan §4.8)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class OutcomesReadPort(Protocol):
    async def list_failed(self, *, limit: int) -> list[dict[str, Any]]:
        """Most recent first, cap ``limit`` (default 100)."""

    async def list_success(self, *, limit: int) -> list[dict[str, Any]]:
        """Most recent first, cap ``limit`` (default 100)."""


@runtime_checkable
class OutcomesWritePort(Protocol):
    async def record_failed(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
        reason: str,
    ) -> None:
        """Persist a terminal failure (``reason`` non-empty)."""

    async def record_success(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
    ) -> None:
        """Persist a terminal success."""
