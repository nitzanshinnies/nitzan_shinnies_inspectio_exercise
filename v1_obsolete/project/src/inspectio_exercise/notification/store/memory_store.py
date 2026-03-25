"""In-process outcomes hot store — swap-in when Redis is not required."""

from __future__ import annotations

from inspectio_exercise.notification import config


class MemoryOutcomesHotStore:
    """Newest-first bounded lists (mirrors Redis LIST LPUSH/LTRIM/LRANGE semantics)."""

    def __init__(
        self,
        *,
        stream_max: int | None = None,
    ) -> None:
        self._stream_max = stream_max if stream_max is not None else config.OUTCOMES_STREAM_MAX
        self._success: list[str] = []
        self._failed: list[str] = []

    async def aclose(self) -> None:
        return None

    async def ping(self) -> None:
        return None

    async def begin_shared_hydration_if_leader(self) -> bool:
        return True

    async def end_shared_hydration(self) -> None:
        return None

    async def clear_all_streams(self) -> None:
        self._success.clear()
        self._failed.clear()

    async def prepend_to_success_stream(self, json_payload: str) -> None:
        self._success.insert(0, json_payload)

    async def prepend_to_failed_stream(self, json_payload: str) -> None:
        self._failed.insert(0, json_payload)

    async def trim_success_stream(self) -> None:
        del self._success[self._stream_max :]

    async def trim_failed_stream(self) -> None:
        del self._failed[self._stream_max :]

    async def get_success_json_rows(self, limit: int) -> list[str]:
        return self._success[:limit]

    async def get_failed_json_rows(self, limit: int) -> list[str]:
        return self._failed[:limit]
