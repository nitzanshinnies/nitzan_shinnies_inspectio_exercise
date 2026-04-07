"""DynamoDB ``BatchWriteItem`` chunking for load tests and bulk ingest."""

from __future__ import annotations

import asyncio
from typing import Any

from inspectio.v3.iter4_dynamo_wal.constants import (
    BATCH_WRITE_ITEM_MAX_ITEMS,
    BATCH_WRITE_RETRY_SLEEP_SEC,
)
from inspectio.v3.iter4_dynamo_wal.dynamo_marshal import marshall_item


async def batch_put_messages(
    client: Any,
    *,
    table_name: str,
    items: list[dict[str, Any]],
) -> None:
    """Chunked ``BatchWriteItem`` (max 25 puts per call). Retries ``UnprocessedItems``.

    For high-TPS load tests: combine with ``botocore_high_throughput_config()`` (pool=500).
    Items must match the ``sms_messages`` item shape (``messageId``, ``shard_id``, …).
    """
    if not items:
        return
    for offset in range(0, len(items), BATCH_WRITE_ITEM_MAX_ITEMS):
        chunk = items[offset : offset + BATCH_WRITE_ITEM_MAX_ITEMS]
        request_items = {
            table_name: [{"PutRequest": {"Item": marshall_item(row)}} for row in chunk],
        }
        response = await client.batch_write_item(RequestItems=request_items)
        unprocessed = response.get("UnprocessedItems", {})
        while unprocessed:
            await asyncio.sleep(BATCH_WRITE_RETRY_SLEEP_SEC)
            response = await client.batch_write_item(RequestItems=unprocessed)
            unprocessed = response.get("UnprocessedItems", {})
