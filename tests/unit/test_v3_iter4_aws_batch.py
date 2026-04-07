"""Botocore pool sizing and batch write helper."""

from __future__ import annotations

import pytest

from inspectio.v3.iter4_dynamo_wal.aws_clients import botocore_high_throughput_config
from inspectio.v3.iter4_dynamo_wal.batch_write import batch_put_messages
from inspectio.v3.iter4_dynamo_wal.constants import (
    BATCH_WRITE_ITEM_MAX_ITEMS,
    MAX_POOL_CONNECTIONS,
    STATUS_PENDING,
)
from inspectio.v3.iter4_dynamo_wal.sharding import message_shard_id

from iter4_constants import TABLE_NAME
from iter4_fake_dynamo import FakeDynamoClient


def test_max_pool_connections_is_500() -> None:
    cfg = botocore_high_throughput_config()
    assert cfg.max_pool_connections == MAX_POOL_CONNECTIONS


@pytest.mark.asyncio
async def test_batch_put_messages_chunks() -> None:
    ddb = FakeDynamoClient()
    rows = []
    for i in range(BATCH_WRITE_ITEM_MAX_ITEMS + 3):
        mid = f"b-{i}"
        shard = message_shard_id(mid, total_shards=8)
        rows.append(
            {
                "messageId": mid,
                "shard_id": shard,
                "attemptCount": 0,
                "nextDueAt": 1,
                "status": STATUS_PENDING,
                "payload": {},
            },
        )
    await batch_put_messages(ddb, table_name=TABLE_NAME, items=rows)
    assert len(ddb._items) == len(rows)
