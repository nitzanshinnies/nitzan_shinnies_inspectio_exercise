"""Unit tests for pluggable outcomes hot store implementations."""

from __future__ import annotations

import json

import pytest

import inspectio_exercise.notification.config as notification_config

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
def test_outcomes_stream_max_covers_default_api_query_limit() -> None:
    """TC-CA-01: hot stream capacity policy is at least the default REST limit."""
    assert notification_config.OUTCOMES_STREAM_MAX >= notification_config.QUERY_LIMIT_DEFAULT


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_store_empty_success_stream() -> None:
    """TC-CA-05: no publishes → empty LRANGE-style read."""
    store = MemoryOutcomesHotStore()
    assert await store.get_success_json_rows(10) == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_store_returns_all_rows_when_limit_exceeds_length() -> None:
    """TC-CA-07: limit larger than stream returns every stored row."""
    store = MemoryOutcomesHotStore(stream_max=20)
    for i in range(3):
        await store.prepend_to_success_stream(json.dumps({"i": i}))
    await store.trim_success_stream()
    rows = await store.get_success_json_rows(500)
    assert len(rows) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_store_allows_duplicate_message_ids_in_stream() -> None:
    """TC-CA-08: duplicate logical ids are visible if published twice (current policy)."""
    store = MemoryOutcomesHotStore(stream_max=20)
    row = json.dumps({"messageId": "dup", "outcome": "success"})
    await store.prepend_to_success_stream(row)
    await store.prepend_to_success_stream(row)
    await store.trim_success_stream()
    got = await store.get_success_json_rows(10)
    assert len(got) == 2
    assert all(json.loads(x)["messageId"] == "dup" for x in got)


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
