"""Orchestration for ``newMessage`` / enqueue API path."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from inspectio.v3.iter4_dynamo_wal.message_repository import (
    MessageRepository,
    epoch_ms,
    next_retry_due_ms,
)
from inspectio.v3.iter4_dynamo_wal.models import NewMessageResponse
from inspectio.v3.iter4_dynamo_wal.sender import SmsSender
from inspectio.v3.iter4_dynamo_wal.sharding import message_shard_id
from inspectio.v3.iter4_dynamo_wal.wal_buffer import WalBuffer


def _is_conditional_failure(exc: ClientError) -> bool:
    code = str(exc.response.get("Error", {}).get("Code", ""))
    return code == "ConditionalCheckFailedException"


async def handle_new_message(
    *,
    message_id: str,
    payload: dict[str, Any],
    repo: MessageRepository,
    sender: SmsSender,
    wal: WalBuffer,
    total_shards: int,
) -> NewMessageResponse:
    existing = await repo.get_by_message_id(message_id)
    if existing is not None:
        return NewMessageResponse(accepted=False, duplicate=True, detail="exists")

    shard_id = message_shard_id(message_id, total_shards=total_shards)
    now_ms = epoch_ms()
    try:
        await repo.put_new_message(
            message_id=message_id,
            shard_id=shard_id,
            payload=payload,
            next_due_at_ms=now_ms,
        )
    except ClientError as exc:
        if _is_conditional_failure(exc):
            return NewMessageResponse(accepted=False, duplicate=True, detail="race")
        raise

    await wal.enqueue(
        {
            "ts_ms": now_ms,
            "type": "enqueue",
            "messageId": message_id,
            "shard_id": shard_id,
            "status": "pending",
            "attemptCount": 0,
        },
    )

    result = await sender.send(message_id, payload)
    if result.ok:
        await repo.mark_success(message_id=message_id, attempt_count_after=1)
        await wal.enqueue(
            {
                "ts_ms": epoch_ms(),
                "type": "success",
                "messageId": message_id,
                "shard_id": shard_id,
                "status": "success",
                "attemptCount": 1,
            },
        )
        return NewMessageResponse(accepted=True, duplicate=False)

    next_due = next_retry_due_ms(epoch_ms())
    await repo.mark_failure_schedule_retry(
        message_id=message_id,
        new_attempt_count=1,
        next_due_at_ms=next_due,
    )
    await wal.enqueue(
        {
            "ts_ms": epoch_ms(),
            "type": "retry_scheduled",
            "messageId": message_id,
            "shard_id": shard_id,
            "status": "pending",
            "attemptCount": 1,
            "nextDueAt": next_due,
            "detail": result.detail,
        },
    )
    return NewMessageResponse(accepted=True, duplicate=False)
