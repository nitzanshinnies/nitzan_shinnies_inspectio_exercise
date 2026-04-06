"""Minimal in-memory DynamoDB stub (marshalled wire format) for unit tests."""

from __future__ import annotations

from typing import Any

from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError


def _unmarshall_values(raw: dict[str, Any]) -> dict[str, Any]:
    des = TypeDeserializer()
    return {key: des.deserialize(value) for key, value in raw.items()}


def _conditional_check_failed() -> ClientError:
    return ClientError(
        error_response={
            "Error": {
                "Code": "ConditionalCheckFailedException",
                "Message": "conditional",
            },
        },
        operation_name="PutItem",
    )


class FakeDynamoClient:
    """Supports get_item, put_item (conditional), update_item (SET list), query."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    async def get_item(self, **kwargs: Any) -> dict[str, Any]:
        from inspectio.v3.iter4_dynamo_wal.dynamo_marshal import (
            marshall_item,
            unmarshall_item,
        )

        key = unmarshall_item(kwargs["Key"])
        mid = str(key["messageId"])
        row = self._items.get(mid)
        if not row:
            return {}
        return {"Item": marshall_item(row)}

    async def put_item(self, **kwargs: Any) -> None:
        from inspectio.v3.iter4_dynamo_wal.dynamo_marshal import unmarshall_item

        item = unmarshall_item(kwargs["Item"])
        mid = str(item["messageId"])
        if kwargs.get("ConditionExpression") == "attribute_not_exists(messageId)":
            if mid in self._items:
                raise _conditional_check_failed()
        self._items[mid] = item

    async def update_item(self, **kwargs: Any) -> None:
        from inspectio.v3.iter4_dynamo_wal.dynamo_marshal import unmarshall_item

        key = unmarshall_item(kwargs["Key"])
        mid = str(key["messageId"])
        row = self._items.get(mid)
        if not row:
            return
        expr = kwargs.get("UpdateExpression", "")
        values = _unmarshall_values(kwargs.get("ExpressionAttributeValues", {}))
        names = kwargs.get("ExpressionAttributeNames", {})
        if expr.startswith("SET "):
            body = expr[4:].strip()
            for part in body.split(","):
                left, _, right = part.partition("=")
                left = left.strip()
                right = right.strip()
                val = values[right]
                if left.startswith("#"):
                    attr = names[left]
                else:
                    attr = left
                row[attr] = val
        self._items[mid] = row

    async def query(self, **kwargs: Any) -> dict[str, Any]:
        from inspectio.v3.iter4_dynamo_wal.dynamo_marshal import marshall_item

        expr = kwargs.get("KeyConditionExpression", "")
        values = _unmarshall_values(kwargs.get("ExpressionAttributeValues", {}))
        names = kwargs.get("ExpressionAttributeNames", {})
        status_attr = names.get("#st", "status")
        want_status = values.get(":pending")
        sid = values.get(":sid")
        due_max = values.get(":due")
        items_out: list[dict[str, Any]] = []
        for row in self._items.values():
            if str(row.get("shard_id")) != str(sid):
                continue
            if kwargs.get("FilterExpression"):
                if row.get(status_attr) != want_status:
                    continue
            if due_max is not None and "nextDueAt <=" in expr:
                if int(row.get("nextDueAt", 0)) > int(due_max):
                    continue
            items_out.append(marshall_item(row))
        return {"Items": items_out}

    def seed(self, row: dict[str, Any]) -> None:
        self._items[str(row["messageId"])] = dict(row)

    async def batch_write_item(self, **kwargs: Any) -> dict[str, Any]:
        from inspectio.v3.iter4_dynamo_wal.dynamo_marshal import unmarshall_item

        request_items = kwargs.get("RequestItems", {})
        for _table, ops in request_items.items():
            for op in ops:
                put = op.get("PutRequest", {}).get("Item")
                if not put:
                    continue
                item = unmarshall_item(put)
                self._items[str(item["messageId"])] = item
        return {}
