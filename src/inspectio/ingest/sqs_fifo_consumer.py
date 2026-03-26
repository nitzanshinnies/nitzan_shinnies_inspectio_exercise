"""SQS FIFO long-poll fetcher for worker ingest."""

from __future__ import annotations

import json
from typing import Any

from inspectio.domain.sharding import owned_shard_range
from inspectio.ingest.ingest_consumer import IngestRawRecord
from inspectio.ingest.schema import MessageIngestedV1


class SqsFifoBatchFetcher:
    """Long-poll SQS FIFO and map messages to ingest rows (§29.6 single worker)."""

    def __init__(
        self,
        *,
        sqs_client: Any,
        queue_url: str,
        worker_index: int,
        worker_replicas: int,
        total_shards: int,
        wait_seconds: int = 20,
        max_messages: int = 10,
    ) -> None:
        self._sqs_client = sqs_client
        self._queue_url = queue_url
        self._worker_index = worker_index
        self._worker_replicas = worker_replicas
        self._total_shards = total_shards
        self._wait_seconds = wait_seconds
        self._max_messages = max_messages
        start, end_excl = owned_shard_range(worker_index, total_shards, worker_replicas)
        self._owned_shards = set(range(start, end_excl))

    async def fetch_records(self) -> list[IngestRawRecord]:
        response = await self._sqs_client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=min(10, self._max_messages),
            WaitTimeSeconds=self._wait_seconds,
            AttributeNames=["All"],
        )
        messages = response.get("Messages", [])
        rows: list[IngestRawRecord] = []
        for msg in messages:
            body = str(msg["Body"])
            receipt = str(msg["ReceiptHandle"])
            message_id = str(msg["MessageId"])
            data = body.encode("utf-8")
            wire = json.loads(body)
            parsed = MessageIngestedV1.from_json_dict(wire)
            if parsed.shard_id not in self._owned_shards:
                await self._sqs_client.change_message_visibility(
                    QueueUrl=self._queue_url,
                    ReceiptHandle=receipt,
                    VisibilityTimeout=0,
                )
                continue
            rows.append(
                IngestRawRecord(
                    checkpoint_shard_id=message_id,
                    sequence_number=message_id,
                    data=data,
                    sqs_receipt_handle=receipt,
                )
            )
        return rows
