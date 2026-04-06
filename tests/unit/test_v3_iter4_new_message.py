"""newMessage path with in-memory DynamoDB fake."""

from __future__ import annotations

import asyncio

import pytest

from inspectio.v3.iter4_dynamo_wal.constants import STATUS_PENDING, STATUS_SUCCESS
from inspectio.v3.iter4_dynamo_wal.message_repository import MessageRepository
from inspectio.v3.iter4_dynamo_wal.new_message_service import handle_new_message
from inspectio.v3.iter4_dynamo_wal.sender import MockSmsSender
from inspectio.v3.iter4_dynamo_wal.wal_buffer import WalBuffer

from iter4_constants import GSI_NAME, TABLE_NAME
from iter4_fake_dynamo import FakeDynamoClient


class FakeS3:
    def __init__(self) -> None:
        self.puts: list[tuple[str, str, bytes]] = []

    async def put_object(self, **kwargs: object) -> None:
        self.puts.append(
            (
                str(kwargs["Bucket"]),
                str(kwargs["Key"]),
                kwargs["Body"],  # type: ignore[arg-type]
            ),
        )


@pytest.mark.asyncio
async def test_new_message_success_persists() -> None:
    ddb = FakeDynamoClient()
    repo = MessageRepository(
        client=ddb,
        table_name=TABLE_NAME,
        gsi_scheduling_index_name=GSI_NAME,
    )
    s3 = FakeS3()
    wal = WalBuffer(
        writer_id="api",
        bucket="b",
        wal_prefix="wal",
        flush_interval_sec=0.05,
    )
    wal.attach_s3_client(s3)
    wal.start_background()
    res = await handle_new_message(
        message_id="m-1",
        payload={"body": "hi"},
        repo=repo,
        sender=MockSmsSender(),
        wal=wal,
        total_shards=16,
    )
    assert res.accepted is True
    row = await repo.get_by_message_id("m-1")
    assert row is not None
    assert row["status"] == STATUS_SUCCESS
    await asyncio.sleep(0.12)
    await wal.stop()
    assert len(s3.puts) >= 1


@pytest.mark.asyncio
async def test_new_message_duplicate() -> None:
    ddb = FakeDynamoClient()
    repo = MessageRepository(
        client=ddb,
        table_name=TABLE_NAME,
        gsi_scheduling_index_name=GSI_NAME,
    )
    wal = WalBuffer(
        writer_id="api", bucket="b", wal_prefix="wal", flush_interval_sec=60.0
    )
    wal.attach_s3_client(FakeS3())
    wal.start_background()
    await handle_new_message(
        message_id="m-dup",
        payload={},
        repo=repo,
        sender=MockSmsSender(),
        wal=wal,
        total_shards=8,
    )
    res2 = await handle_new_message(
        message_id="m-dup",
        payload={},
        repo=repo,
        sender=MockSmsSender(),
        wal=wal,
        total_shards=8,
    )
    assert res2.duplicate is True
    await wal.stop()


@pytest.mark.asyncio
async def test_new_message_first_send_fails_schedules_retry() -> None:
    ddb = FakeDynamoClient()
    repo = MessageRepository(
        client=ddb,
        table_name=TABLE_NAME,
        gsi_scheduling_index_name=GSI_NAME,
    )
    wal = WalBuffer(
        writer_id="api", bucket="b", wal_prefix="wal", flush_interval_sec=60.0
    )
    wal.attach_s3_client(FakeS3())
    wal.start_background()
    res = await handle_new_message(
        message_id="m-fail",
        payload={"fail": True},
        repo=repo,
        sender=MockSmsSender(),
        wal=wal,
        total_shards=8,
    )
    assert res.accepted is True
    row = await repo.get_by_message_id("m-fail")
    assert row is not None
    assert row["status"] == STATUS_PENDING
    assert int(row["attemptCount"]) == 1
    await wal.stop()
