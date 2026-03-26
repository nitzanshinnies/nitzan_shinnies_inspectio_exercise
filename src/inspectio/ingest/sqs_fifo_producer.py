"""SQS FIFO producer for API admission path."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import aioboto3

from inspectio.ingest.ingest_producer import (
    IngestPutInput,
    IngestPutResult,
    IngestUnavailableError,
    partition_key_for_shard,
)
from inspectio.ingest.schema import MessageIngestPayload, MessageIngestedV1
from inspectio.settings import Settings

MAX_SQS_FIFO_SEND_BATCH = 10


def _deduplication_id(idempotency_key: str) -> str:
    """FIFO MessageDeduplicationId (max 128 chars)."""
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


class SqsFifoIngestProducer:
    """AWS SQS FIFO send_message_batch implementation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def put_messages(
        self, messages: list[IngestPutInput]
    ) -> list[IngestPutResult]:
        queue_url = self._settings.inspectio_ingest_queue_url.strip()
        if not queue_url:
            msg = "INSPECTIO_INGEST_QUEUE_URL must be set for ingest"
            raise IngestUnavailableError(msg)

        out: list[IngestPutResult] = []
        session = aioboto3.Session()
        try:
            async with session.client(
                "sqs", region_name=self._settings.inspectio_aws_region
            ) as client:
                for start in range(0, len(messages), MAX_SQS_FIFO_SEND_BATCH):
                    chunk = messages[start : start + MAX_SQS_FIFO_SEND_BATCH]
                    chunk_out = await _send_fifo_batch(client, queue_url, chunk)
                    out.extend(chunk_out)
        except IngestUnavailableError:
            raise
        except Exception as exc:  # pragma: no cover - provider failure mapping
            raise IngestUnavailableError(str(exc)) from exc

        return out


async def _send_fifo_batch(
    client: Any,
    queue_url: str,
    chunk: list[IngestPutInput],
) -> list[IngestPutResult]:
    batch = _build_batch_entries(chunk)
    response = await client.send_message_batch(
        QueueUrl=queue_url,
        Entries=batch,
    )
    message_id_by_idx: dict[int, str | None] = {}
    for row in response.get("Successful", []):
        message_id_by_idx[int(row["Id"])] = (
            str(row["MessageId"]) if row.get("MessageId") else None
        )
    for fail in response.get("Failed", []):
        idx = int(fail["Id"])
        item = chunk[idx]
        mid = await _send_single_fifo_message(client, queue_url, item)
        message_id_by_idx[idx] = mid
    results: list[IngestPutResult] = []
    for idx, item in enumerate(chunk):
        mid = message_id_by_idx.get(idx)
        results.append(
            IngestPutResult(
                message_id=item.message_id,
                shard_id=item.shard_id,
                ingest_sequence=mid,
            )
        )
    return results


async def _send_single_fifo_message(
    client: Any,
    queue_url: str,
    item: IngestPutInput,
) -> str | None:
    value = MessageIngestedV1(
        message_id=item.message_id,
        payload=MessageIngestPayload(body=item.payload_body, to=item.payload_to),
        received_at_ms=item.received_at_ms,
        shard_id=item.shard_id,
        idempotency_key=item.idempotency_key,
    ).to_json_dict()
    body = json.dumps(value, separators=(",", ":"), sort_keys=True)
    resp = await client.send_message(
        QueueUrl=queue_url,
        MessageBody=body,
        MessageGroupId=partition_key_for_shard(item.shard_id),
        MessageDeduplicationId=_deduplication_id(item.idempotency_key),
    )
    mid = resp.get("MessageId")
    return str(mid) if mid else None


def _build_batch_entries(messages: list[IngestPutInput]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for idx, item in enumerate(messages):
        value = MessageIngestedV1(
            message_id=item.message_id,
            payload=MessageIngestPayload(body=item.payload_body, to=item.payload_to),
            received_at_ms=item.received_at_ms,
            shard_id=item.shard_id,
            idempotency_key=item.idempotency_key,
        ).to_json_dict()
        body = json.dumps(value, separators=(",", ":"), sort_keys=True)
        group = partition_key_for_shard(item.shard_id)
        entries.append(
            {
                "Id": str(idx),
                "MessageBody": body,
                "MessageGroupId": group,
                "MessageDeduplicationId": _deduplication_id(item.idempotency_key),
            }
        )
    return entries
