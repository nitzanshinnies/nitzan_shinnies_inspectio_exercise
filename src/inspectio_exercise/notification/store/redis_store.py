"""Redis-backed implementation of OutcomesHotStore."""

from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import RedisError

from inspectio_exercise.notification import config
from inspectio_exercise.notification.store.interface import OutcomesStoreError


class RedisOutcomesHotStore:
    def __init__(
        self,
        client: Redis,
        *,
        owns_client: bool,
        failed_key: str | None = None,
        stream_max: int | None = None,
        success_key: str | None = None,
    ) -> None:
        self._client = client
        self._failed_key = failed_key if failed_key is not None else config.REDIS_KEY_FAILED
        self._owns_client = owns_client
        self._stream_max = stream_max if stream_max is not None else config.OUTCOMES_STREAM_MAX
        self._success_key = success_key if success_key is not None else config.REDIS_KEY_SUCCESS

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def ping(self) -> None:
        try:
            await self._client.ping()
        except RedisError as exc:
            raise OutcomesStoreError(str(exc)) from exc

    async def clear_all_streams(self) -> None:
        try:
            await self._client.delete(self._success_key, self._failed_key)
        except RedisError as exc:
            raise OutcomesStoreError(str(exc)) from exc

    async def prepend_to_success_stream(self, json_payload: str) -> None:
        try:
            await self._client.lpush(self._success_key, json_payload)
        except RedisError as exc:
            raise OutcomesStoreError(str(exc)) from exc

    async def prepend_to_failed_stream(self, json_payload: str) -> None:
        try:
            await self._client.lpush(self._failed_key, json_payload)
        except RedisError as exc:
            raise OutcomesStoreError(str(exc)) from exc

    async def trim_success_stream(self) -> None:
        try:
            await self._client.ltrim(self._success_key, 0, self._stream_max - 1)
        except RedisError as exc:
            raise OutcomesStoreError(str(exc)) from exc

    async def trim_failed_stream(self) -> None:
        try:
            await self._client.ltrim(self._failed_key, 0, self._stream_max - 1)
        except RedisError as exc:
            raise OutcomesStoreError(str(exc)) from exc

    async def get_success_json_rows(self, limit: int) -> list[str]:
        try:
            raw = await self._client.lrange(self._success_key, 0, limit - 1)
        except RedisError as exc:
            raise OutcomesStoreError(str(exc)) from exc
        return list(raw)

    async def get_failed_json_rows(self, limit: int) -> list[str]:
        try:
            raw = await self._client.lrange(self._failed_key, 0, limit - 1)
        except RedisError as exc:
            raise OutcomesStoreError(str(exc)) from exc
        return list(raw)
