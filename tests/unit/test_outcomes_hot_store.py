"""Unit tests for pluggable outcomes hot store implementations."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fakeredis")
from fakeredis import FakeAsyncRedis

from inspectio_exercise.notification.store.memory_store import MemoryOutcomesHotStore
from inspectio_exercise.notification.store.redis_store import RedisOutcomesHotStore


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_store_prepend_trim_newest_first() -> None:
    store = MemoryOutcomesHotStore(stream_max=10)
    await store.prepend_to_success_stream(json.dumps({"id": "a"}))
    await store.prepend_to_success_stream(json.dumps({"id": "b"}))
    await store.trim_success_stream()
    rows = await store.get_success_json_rows(5)
    assert [json.loads(x)["id"] for x in rows] == ["b", "a"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_redis_store_matches_memory_semantics() -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    store = RedisOutcomesHotStore(redis, owns_client=False, stream_max=10)
    await store.prepend_to_success_stream(json.dumps({"id": "a"}))
    await store.prepend_to_success_stream(json.dumps({"id": "b"}))
    await store.trim_success_stream()
    rows = await store.get_success_json_rows(5)
    assert [json.loads(x)["id"] for x in rows] == ["b", "a"]
