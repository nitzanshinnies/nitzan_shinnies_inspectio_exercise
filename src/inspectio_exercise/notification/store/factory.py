"""Construct OutcomesHotStore from configuration (plugin selection)."""

from __future__ import annotations

from redis import asyncio as redis_asyncio

from inspectio_exercise.notification.store.interface import OutcomesHotStore, OutcomesStoreError
from inspectio_exercise.notification.store.memory_store import MemoryOutcomesHotStore
from inspectio_exercise.notification.store.redis_store import RedisOutcomesHotStore


async def create_outcomes_store(
    *,
    backend: str,
    redis_url: str,
) -> OutcomesHotStore:
    """Build and validate a store for the given ``backend`` name."""
    normalized = backend.strip().lower()
    if normalized == "memory":
        return MemoryOutcomesHotStore()
    if normalized == "redis":
        client = redis_asyncio.from_url(redis_url, decode_responses=True)
        store = RedisOutcomesHotStore(client, owns_client=True)
        try:
            await store.ping()
        except OutcomesStoreError:
            await store.aclose()
            raise
        return store
    raise ValueError(f"unsupported OUTCOMES_STORE_BACKEND: {backend!r}")
