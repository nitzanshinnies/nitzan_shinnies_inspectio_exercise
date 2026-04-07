"""Worker scheduler with in-memory DynamoDB fake."""

from __future__ import annotations

import asyncio
import time

import pytest

from inspectio.v3.iter4_dynamo_wal.constants import (
    MAX_SEND_ATTEMPTS,
    STATUS_FAILED,
    STATUS_SUCCESS,
    TICK_INTERVAL_SEC,
)
from inspectio.v3.iter4_dynamo_wal.message_repository import MessageRepository, epoch_ms
from inspectio.v3.iter4_dynamo_wal.sender import MockSmsSender, SmsSendResult
from inspectio.v3.iter4_dynamo_wal.sharding import message_shard_id
from inspectio.v3.iter4_dynamo_wal.wal_buffer import WalBuffer
from inspectio.v3.iter4_dynamo_wal.worker.recovery import load_heap_from_dynamo
from inspectio.v3.iter4_dynamo_wal.worker.scheduler_loop import WorkerScheduler

from iter4_constants import GSI_NAME, TABLE_NAME
from iter4_fake_dynamo import FakeDynamoClient


class FakeS3:
    async def put_object(self, **kwargs: object) -> None:
        return None


@pytest.mark.asyncio
async def test_worker_retries_until_success() -> None:
    ddb = FakeDynamoClient()
    repo = MessageRepository(
        client=ddb,
        table_name=TABLE_NAME,
        gsi_scheduling_index_name=GSI_NAME,
    )
    mid = "retry-1"
    shard = message_shard_id(mid, total_shards=4)
    await repo.put_new_message_unconditional(
        message_id=mid,
        shard_id=shard,
        payload={"fail_until": epoch_ms() + 2},
        next_due_at_ms=epoch_ms(),
        attempt_count=0,
    )
    wal = WalBuffer(
        writer_id="worker-0",
        bucket="b",
        wal_prefix="wal",
        flush_interval_sec=60.0,
    )
    wal.attach_s3_client(FakeS3())

    class FlakySender(MockSmsSender):
        async def send(self, message_id: str, payload: dict) -> SmsSendResult:  # type: ignore[override]
            if epoch_ms() < int(payload.get("fail_until", 0)):
                return SmsSendResult(ok=False, detail="retry")
            return SmsSendResult(ok=True)

    heap: list[tuple[int, str]] = []
    scheduled: set[str] = set()
    await load_heap_from_dynamo(
        repo=repo,
        shard_ids=[shard],
        heap=heap,
        scheduled_ids=scheduled,
    )
    scheduler = WorkerScheduler(
        repo=repo,
        sender=FlakySender(),
        wal=wal,
        owned_shard_ids=[shard],
        reconcile_interval_sec=0.05,
    )
    scheduler.adopt_state(heap, scheduled)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        await scheduler.reconcile_once()
        await scheduler.tick_once()
        row = await repo.get_by_message_id(mid)
        if row and str(row.get("status")) == STATUS_SUCCESS:
            break
        await asyncio.sleep(0.02)
    final = await repo.get_by_message_id(mid)
    assert final is not None
    assert final["status"] == STATUS_SUCCESS


@pytest.mark.asyncio
async def test_worker_marks_failed_after_max_attempts() -> None:
    ddb = FakeDynamoClient()
    repo = MessageRepository(
        client=ddb,
        table_name=TABLE_NAME,
        gsi_scheduling_index_name=GSI_NAME,
    )
    mid = "dead-1"
    shard = message_shard_id(mid, total_shards=4)
    await repo.put_new_message_unconditional(
        message_id=mid,
        shard_id=shard,
        payload={"fail": True},
        next_due_at_ms=epoch_ms(),
        attempt_count=MAX_SEND_ATTEMPTS - 1,
    )
    wal = WalBuffer(
        writer_id="w", bucket="b", wal_prefix="wal", flush_interval_sec=60.0
    )
    wal.attach_s3_client(FakeS3())
    heap = [(epoch_ms(), mid)]
    scheduled = {mid}
    scheduler = WorkerScheduler(
        repo=repo,
        sender=MockSmsSender(),
        wal=wal,
        owned_shard_ids=[shard],
        reconcile_interval_sec=1.0,
    )
    scheduler.adopt_state(heap, scheduled)
    await scheduler.tick_once()
    final = await repo.get_by_message_id(mid)
    assert final is not None
    assert final["status"] == STATUS_FAILED


@pytest.mark.asyncio
async def test_slow_send_tick_takes_at_least_tick_interval() -> None:
    ddb = FakeDynamoClient()
    repo = MessageRepository(
        client=ddb,
        table_name=TABLE_NAME,
        gsi_scheduling_index_name=GSI_NAME,
    )
    mid = "slow-1"
    shard = message_shard_id(mid, total_shards=4)
    await repo.put_new_message_unconditional(
        message_id=mid,
        shard_id=shard,
        payload={},
        next_due_at_ms=epoch_ms(),
    )
    wal = WalBuffer(
        writer_id="w", bucket="b", wal_prefix="wal", flush_interval_sec=60.0
    )
    wal.attach_s3_client(FakeS3())

    class SlowSender(MockSmsSender):
        async def send(self, message_id: str, payload: dict) -> SmsSendResult:  # type: ignore[override]
            await asyncio.sleep(TICK_INTERVAL_SEC * 2)
            return await super().send(message_id, payload)

    heap = [(epoch_ms(), mid)]
    scheduled = {mid}
    scheduler = WorkerScheduler(
        repo=repo,
        sender=SlowSender(),
        wal=wal,
        owned_shard_ids=[shard],
        reconcile_interval_sec=10.0,
    )
    scheduler.adopt_state(heap, scheduled)
    t0 = time.monotonic()
    await scheduler.tick_once()
    assert time.monotonic() - t0 >= TICK_INTERVAL_SEC
