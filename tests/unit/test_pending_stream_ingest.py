"""Redis Stream pending ingest → persistence flush (plans: optional hot-path buffer)."""

from __future__ import annotations

from typing import cast

import pytest

pytest.importorskip("fakeredis")
from fakeredis import aioredis as faker_aioredis

from inspectio_exercise.api.pending_stream_ingest import (
    drain_pending_stream_once,
    ensure_pending_stream_group,
    stage_key_for_pending,
    stage_pending_writes,
    stage_pending_writes_with_policy,
)
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.persistence.object_write import ObjectWrite


class _StubPersistenceClient:
    """Minimal stand-in for ``PersistenceHttpClient`` (only ``put_objects`` used)."""

    def __init__(self) -> None:
        self.batches: list[list[ObjectWrite]] = []

    async def put_objects(self, items: list[ObjectWrite] | tuple[ObjectWrite, ...]) -> None:
        self.batches.append(list(items))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stage_then_drain_flushes_put_objects_and_clears_staging() -> None:
    redis = faker_aioredis.FakeRedis(decode_responses=False)
    await ensure_pending_stream_group(redis)
    k1 = "state/pending/shard-0/one.json"
    k2 = "state/pending/shard-0/two.json"
    b1 = b'{"messageId":"one"}'
    b2 = b'{"messageId":"two"}'
    await stage_pending_writes(
        redis,
        [
            ObjectWrite(key=k1, body=b1, content_type="application/json"),
            ObjectWrite(key=k2, body=b2, content_type="application/json"),
        ],
    )
    assert await redis.get(stage_key_for_pending(k1)) == b1
    stub = _StubPersistenceClient()
    await drain_pending_stream_once(redis, cast(PersistenceHttpClient, stub))
    assert len(stub.batches) == 1
    keys = {ow.key for ow in stub.batches[0]}
    assert keys == {k1, k2}
    assert await redis.get(stage_key_for_pending(k1)) is None
    assert await redis.get(stage_key_for_pending(k2)) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stage_empty_is_noop() -> None:
    redis = faker_aioredis.FakeRedis(decode_responses=False)
    await stage_pending_writes(redis, [])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stage_with_no_flush_policy_keeps_item_staged_only() -> None:
    redis = faker_aioredis.FakeRedis(decode_responses=False)
    await ensure_pending_stream_group(redis)
    key = "state/pending/shard-0/no-flush.json"
    body = b'{"messageId":"no-flush"}'
    await stage_pending_writes_with_policy(
        redis,
        [ObjectWrite(key=key, body=body, content_type="application/json")],
        enqueue_for_flush=False,
    )
    assert await redis.get(stage_key_for_pending(key)) == body
    stub = _StubPersistenceClient()
    await drain_pending_stream_once(redis, cast(PersistenceHttpClient, stub))
    assert stub.batches == []
