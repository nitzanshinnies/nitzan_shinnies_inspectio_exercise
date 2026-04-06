"""DynamoDB ``BatchWriteItem`` chunking for load tests and bulk ingest."""

from __future__ import annotations

from typing import Any

from inspectio.v3.iter4_dynamo_wal.constants import BATCH_WRITE_ITEM_MAX_ITEMS
from inspectio.v3.iter4_dynamo_wal.dynamo_marshal import marshall_item


async def batch_put_messages(
    client: Any,
    *,
    table_name: str,
    items: list[dict[str, Any]],
) -> None:
    """Best-effort put; caller supplies fully-shaped attribute dicts (Python types)."""
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
            response = await client.batch_write_item(RequestItems=unprocessed)
            unprocessed = response.get("UnprocessedItems", {})
