"""Redis-backed implementation of OutcomesHotStore."""

from __future__ import annotations

import asyncio
import contextlib
import time

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

    async def _streams_non_empty(self) -> bool:
        try:
            sc = await self._client.llen(self._success_key)
            fc = await self._client.llen(self._failed_key)
        except RedisError as exc:
            raise OutcomesStoreError(str(exc)) from exc
        return sc > 0 or fc > 0

    async def begin_shared_hydration_if_leader(self) -> bool:
        """Acquire leader lock when lists are empty, or wait for a peer to hydrate shared Redis."""
        lock_key = config.HYDRATION_REDIS_LOCK_KEY
        ttl = config.HYDRATION_REDIS_LOCK_TTL_SEC
        wait_sec = config.HYDRATION_REDIS_WAIT_PEER_SEC

        async def try_lock() -> bool:
            try:
                return bool(await self._client.set(lock_key, "1", nx=True, ex=ttl))
            except RedisError as exc:
                raise OutcomesStoreError(str(exc)) from exc

        async def release_lock() -> None:
            with contextlib.suppress(RedisError):
                await self._client.delete(lock_key)

        got = await try_lock()
        if not got:
            deadline = time.monotonic() + wait_sec
            while time.monotonic() < deadline:
                if await self._streams_non_empty():
                    return False
                await asyncio.sleep(0.15)
            got = await try_lock()
            if not got:
                return False

        try:
            if await self._streams_non_empty():
                await release_lock()
                return False
            return True
        except Exception:
            await release_lock()
            raise

    async def end_shared_hydration(self) -> None:
        with contextlib.suppress(RedisError):
            await self._client.delete(config.HYDRATION_REDIS_LOCK_KEY)

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
