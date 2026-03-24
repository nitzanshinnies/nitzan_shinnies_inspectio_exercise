"""Worker read-through staging before S3 (Redis stream ingest mode)."""

from __future__ import annotations

import pytest

pytest.importorskip("fakeredis")
from fakeredis import aioredis as faker_aioredis

from inspectio_exercise.api.pending_stream_ingest import stage_key_for_pending
from inspectio_exercise.worker.staging_persistence import StagingPersistence
from tests.fakes import RecordingPersistence

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_get_object_prefers_redis_staging() -> None:
    redis = faker_aioredis.FakeRedis(decode_responses=False)
    inner = RecordingPersistence()
    key = "state/pending/shard-1/x.json"
    staged = b'{"messageId":"x","status":"pending"}'
    await redis.set(stage_key_for_pending(key), staged)
    sp = StagingPersistence(redis, inner)
    assert await sp.get_object(key) == staged
    assert inner.gotten == []


@pytest.mark.asyncio
async def test_get_object_falls_back_to_inner() -> None:
    redis = faker_aioredis.FakeRedis(decode_responses=False)
    inner = RecordingPersistence()
    key = "state/pending/shard-1/y.json"
    await inner.put_object(key, b"from-inner")
    sp = StagingPersistence(redis, inner)
    assert await sp.get_object(key) == b"from-inner"


@pytest.mark.asyncio
async def test_delete_object_clears_staging_and_inner() -> None:
    redis = faker_aioredis.FakeRedis(decode_responses=False)
    inner = RecordingPersistence()
    key = "state/pending/shard-1/z.json"
    await redis.set(stage_key_for_pending(key), b"z")
    await inner.put_object(key, b"z")
    sp = StagingPersistence(redis, inner)
    await sp.delete_object(key)
    assert await redis.get(stage_key_for_pending(key)) is None
    with pytest.raises(KeyError):
        await inner.get_object(key)


@pytest.mark.asyncio
async def test_list_prefix_merges_inner_and_staging_rows() -> None:
    redis = faker_aioredis.FakeRedis(decode_responses=False)
    inner = RecordingPersistence()
    key_staged = "state/pending/shard-1/staged.json"
    key_inner = "state/pending/shard-1/inner.json"
    await redis.set(stage_key_for_pending(key_staged), b"staged")
    await inner.put_object(key_inner, b"inner")
    sp = StagingPersistence(redis, inner)
    rows = await sp.list_prefix("state/pending/shard-1/")
    keys = [row["Key"] for row in rows]
    assert keys == sorted([key_inner, key_staged])


@pytest.mark.asyncio
async def test_put_object_clears_staging_for_same_key() -> None:
    redis = faker_aioredis.FakeRedis(decode_responses=False)
    inner = RecordingPersistence()
    key = "state/pending/shard-1/retry.json"
    await redis.set(stage_key_for_pending(key), b'{"attemptCount":0}')
    sp = StagingPersistence(redis, inner)
    await sp.put_object(key, b'{"attemptCount":1}')
    assert await redis.get(stage_key_for_pending(key)) is None
    assert await inner.get_object(key) == b'{"attemptCount":1}'
