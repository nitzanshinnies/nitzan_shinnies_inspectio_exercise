"""Abstract hot outcomes cache — Redis or other backends implement this contract."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class OutcomesStoreError(Exception):
    """Hot outcomes store unavailable or operation failed."""


@runtime_checkable
class OutcomesHotStore(Protocol):
    """Bounded newest-first success/failed JSON rows (see plans/NOTIFICATION_SERVICE.md §4)."""

    async def aclose(self) -> None:
        """Release resources when this store owns its connection (no-op otherwise)."""

    async def ping(self) -> None:
        """Verify the store is reachable; raise OutcomesStoreError on failure."""

    async def clear_all_streams(self) -> None:
        """Remove both outcome streams before hydration."""

    async def prepend_to_success_stream(self, json_payload: str) -> None:
        """Prepend one JSON row to the success stream (newest at head)."""

    async def prepend_to_failed_stream(self, json_payload: str) -> None:
        """Prepend one JSON row to the failed stream (newest at head)."""

    async def trim_success_stream(self) -> None:
        """Trim success stream to the configured maximum length."""

    async def trim_failed_stream(self) -> None:
        """Trim failed stream to the configured maximum length."""

    async def get_success_json_rows(self, limit: int) -> list[str]:
        """Return up to ``limit`` JSON strings, newest first."""

    async def get_failed_json_rows(self, limit: int) -> list[str]:
        """Return up to ``limit`` JSON strings, newest first."""
