"""Redis-backed outcomes store: single-replica S3 hydration when sharing one Redis."""

from __future__ import annotations

import pytest

pytest.importorskip("fakeredis")
from fakeredis import FakeAsyncRedis

from inspectio_exercise.notification.store.redis_store import RedisOutcomesHotStore

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_begin_hydration_leader_releases_lock() -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    store = RedisOutcomesHotStore(redis, owns_client=False)
    assert await store.begin_shared_hydration_if_leader() is True
    await store.end_shared_hydration()
    assert await store.begin_shared_hydration_if_leader() is True
    await store.end_shared_hydration()


@pytest.mark.asyncio
async def test_begin_hydration_skips_when_streams_already_warm() -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    leader = RedisOutcomesHotStore(redis, owns_client=False)
    assert await leader.begin_shared_hydration_if_leader() is True
    await leader.prepend_to_success_stream('{"notificationId":"x","outcome":"success"}')
    await leader.end_shared_hydration()

    follower = RedisOutcomesHotStore(redis, owns_client=False)
    assert await follower.begin_shared_hydration_if_leader() is False
