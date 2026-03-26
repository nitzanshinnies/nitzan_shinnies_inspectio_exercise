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
