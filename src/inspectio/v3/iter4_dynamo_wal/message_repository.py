"""DynamoDB access for ``sms_messages`` (PK ``messageId``, GSI ``SchedulingIndex``)."""

from __future__ import annotations

import time
from typing import Any

from inspectio.v3.iter4_dynamo_wal.constants import (
    MAX_SEND_ATTEMPTS,
    RETRY_DELAY_MS,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SUCCESS,
)
from inspectio.v3.iter4_dynamo_wal.dynamo_marshal import marshall_item, unmarshall_item


def epoch_ms() -> int:
    return int(time.time() * 1000)


class MessageRepository:
    def __init__(
        self,
        *,
        client: Any,
        table_name: str,
        gsi_scheduling_index_name: str,
    ) -> None:
        self._client = client
        self._table = table_name
        self._gsi = gsi_scheduling_index_name

    async def get_by_message_id(self, message_id: str) -> dict[str, Any] | None:
        response = await self._client.get_item(
            TableName=self._table,
            Key=marshall_item({"messageId": message_id}),
            ConsistentRead=True,
        )
        raw = response.get("Item")
        if not raw:
            return None
        return unmarshall_item(raw)

    async def put_new_message(
        self,
        *,
        message_id: str,
        shard_id: str,
        payload: dict[str, Any],
        next_due_at_ms: int,
    ) -> None:
        item = {
            "messageId": message_id,
            "shard_id": shard_id,
            "attemptCount": 0,
            "nextDueAt": next_due_at_ms,
            "status": STATUS_PENDING,
            "payload": payload,
        }
        await self._client.put_item(
            TableName=self._table,
            Item=marshall_item(item),
            ConditionExpression="attribute_not_exists(messageId)",
        )

    async def put_new_message_unconditional(
        self,
        *,
        message_id: str,
        shard_id: str,
        payload: dict[str, Any],
        next_due_at_ms: int,
        attempt_count: int = 0,
        status: str = STATUS_PENDING,
    ) -> None:
        """For load tests / batch ingest (no idempotency condition)."""
        item = {
            "messageId": message_id,
            "shard_id": shard_id,
            "attemptCount": attempt_count,
            "nextDueAt": next_due_at_ms,
            "status": status,
            "payload": payload,
        }
        await self._client.put_item(TableName=self._table, Item=marshall_item(item))

    async def mark_success(self, *, message_id: str, attempt_count_after: int) -> None:
        await self._client.update_item(
            TableName=self._table,
            Key=marshall_item({"messageId": message_id}),
            UpdateExpression="SET #s = :ok, attemptCount = :ac, nextDueAt = :due",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=marshall_item(
                {
                    ":ok": STATUS_SUCCESS,
                    ":ac": attempt_count_after,
                    ":due": epoch_ms(),
                },
            ),
        )

    async def mark_failure_schedule_retry(
        self,
        *,
        message_id: str,
        new_attempt_count: int,
        next_due_at_ms: int,
    ) -> None:
        if new_attempt_count >= MAX_SEND_ATTEMPTS:
            await self.mark_permanently_failed(
                message_id=message_id,
                attempt_count=new_attempt_count,
            )
            return
        await self._client.update_item(
            TableName=self._table,
            Key=marshall_item({"messageId": message_id}),
            UpdateExpression="SET attemptCount = :ac, nextDueAt = :due, #s = :pending",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues=marshall_item(
                {
                    ":ac": new_attempt_count,
                    ":due": next_due_at_ms,
                    ":pending": STATUS_PENDING,
                },
            ),
        )

    async def mark_permanently_failed(
        self,
        *,
        message_id: str,
        attempt_count: int | None = None,
    ) -> None:
        """Mark terminal failure; optional ``attempt_count`` (e.g. 6) for audit."""
        names: dict[str, str] = {"#s": "status"}
        values: dict[str, Any] = {
            ":f": STATUS_FAILED,
            ":due": epoch_ms(),
        }
        expr = "SET #s = :f, nextDueAt = :due"
        if attempt_count is not None:
            expr += ", attemptCount = :ac"
            values[":ac"] = attempt_count
        await self._client.update_item(
            TableName=self._table,
            Key=marshall_item({"messageId": message_id}),
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=marshall_item(values),
        )

    async def load_all_pending_for_shard(self, shard_id: str) -> list[dict[str, Any]]:
        """Boot-time recovery: all pending rows for a shard (GSI query)."""
        items: list[dict[str, Any]] = []
        exclusive_start_key: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "TableName": self._table,
                "IndexName": self._gsi,
                "KeyConditionExpression": "shard_id = :sid",
                "FilterExpression": "#st = :pending",
                "ExpressionAttributeNames": {"#st": "status"},
                "ExpressionAttributeValues": marshall_item(
                    {
                        ":sid": shard_id,
                        ":pending": STATUS_PENDING,
                    },
                ),
            }
            if exclusive_start_key:
                kwargs["ExclusiveStartKey"] = exclusive_start_key
            response = await self._client.query(**kwargs)
            for row in response.get("Items", []):
                items.append(unmarshall_item(row))
            exclusive_start_key = response.get("LastEvaluatedKey")
            if not exclusive_start_key:
                break
        return items

    async def load_due_pending_for_shard(
        self,
        shard_id: str,
        *,
        due_before_ms: int,
    ) -> list[dict[str, Any]]:
        """Reconciliation: pending rows due by ``due_before_ms`` (inclusive)."""
        items: list[dict[str, Any]] = []
        exclusive_start_key: dict[str, Any] | None = None
        while True:
            kwargs: dict[str, Any] = {
                "TableName": self._table,
                "IndexName": self._gsi,
                "KeyConditionExpression": "shard_id = :sid AND nextDueAt <= :due",
                "FilterExpression": "#st = :pending",
                "ExpressionAttributeNames": {"#st": "status"},
                "ExpressionAttributeValues": marshall_item(
                    {
                        ":sid": shard_id,
                        ":due": due_before_ms,
                        ":pending": STATUS_PENDING,
                    },
                ),
            }
            if exclusive_start_key:
                kwargs["ExclusiveStartKey"] = exclusive_start_key
            response = await self._client.query(**kwargs)
            for row in response.get("Items", []):
                items.append(unmarshall_item(row))
            exclusive_start_key = response.get("LastEvaluatedKey")
            if not exclusive_start_key:
                break
        return items


def next_retry_due_ms(now_ms: int) -> int:
    return now_ms + RETRY_DELAY_MS
