"""SQS FIFO producer for API admission path (replaces Kinesis PutRecords)."""

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
                    batch = _build_batch_entries(chunk)
                    response = await client.send_message_batch(
                        QueueUrl=queue_url,
                        Entries=batch,
                    )
                    _raise_if_batch_failures(response)
                    successful = response.get("Successful", [])
                    by_id = {str(x["Id"]): x for x in successful}
                    for idx, item in enumerate(chunk):
                        row = by_id.get(str(idx))
                        mid = (
                            str(row["MessageId"])
                            if row and row.get("MessageId")
                            else None
                        )
                        out.append(
                            IngestPutResult(
                                message_id=item.message_id,
                                shard_id=item.shard_id,
                                ingest_sequence=mid,
                            )
                        )
        except IngestUnavailableError:
            raise
        except Exception as exc:  # pragma: no cover - provider failure mapping
            raise IngestUnavailableError(str(exc)) from exc

        return out


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


def _raise_if_batch_failures(response: dict[str, Any]) -> None:
    failed = response.get("Failed", [])
    if not failed:
        return
    first = failed[0]
    code = first.get("Code", "unknown")
    msg = first.get("Message", "")
    raise IngestUnavailableError(f"{code}: {msg}")
