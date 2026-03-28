"""SQS FIFO producer for API admission path (§17, SQS-P1)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from inspectio.ingest.ingest_producer import (
    IngestPutInput,
    IngestPutResult,
    IngestUnavailableError,
    partition_key_for_shard,
)
from inspectio.ingest.schema import MessageIngestPayload, MessageIngestedV1
from inspectio.settings import Settings

MAX_SQS_FIFO_SEND_BATCH = 10
SQS_SEND_MAX_ATTEMPTS = 8
SQS_SEND_BASE_DELAY_SEC = 0.05
SQS_SEND_MAX_DELAY_SEC = 2.0


def _deduplication_id(idempotency_key: str) -> str:
    """FIFO MessageDeduplicationId (max 128 chars)."""
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


def _is_sqs_transient_error(exc: ClientError) -> bool:
    code = exc.response.get("Error", {}).get("Code", "")
    return code in (
        "Throttling",
        "ThrottlingException",
        "RequestThrottled",
        "TooManyRequestsException",
        "ServiceUnavailable",
        "InternalError",
        "SlowDown",
    )


class SqsFifoIngestProducer:
    """AWS SQS FIFO `send_message_batch` with parallel batches across message groups."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def put_messages(
        self, messages: list[IngestPutInput]
    ) -> list[IngestPutResult]:
        queue_url = self._settings.ingest_queue_url.strip()
        if not queue_url:
            msg = "INSPECTIO_INGEST_QUEUE_URL must be set for ingest"
            raise IngestUnavailableError(msg)

        if not messages:
            return []

        max_groups = self._settings.max_sqs_fifo_inflight_groups
        semaphore = asyncio.Semaphore(max_groups)

        buckets: dict[str, list[tuple[int, IngestPutInput]]] = defaultdict(list)
        for i, item in enumerate(messages):
            group = partition_key_for_shard(item.shard_id)
            buckets[group].append((i, item))

        session = aioboto3.Session()
        try:
            client_kw: dict[str, Any] = {"region_name": self._settings.aws_region}
            if self._settings.aws_endpoint_url:
                client_kw["endpoint_url"] = self._settings.aws_endpoint_url
            async with session.client("sqs", **client_kw) as client:

                async def run_group(
                    indexed: list[tuple[int, IngestPutInput]],
                ) -> list[tuple[int, IngestPutResult]]:
                    async with semaphore:
                        out: list[tuple[int, IngestPutResult]] = []
                        for start in range(0, len(indexed), MAX_SQS_FIFO_SEND_BATCH):
                            chunk = indexed[start : start + MAX_SQS_FIFO_SEND_BATCH]
                            items_only = [m for _, m in chunk]
                            batch_out = await _send_fifo_batch(
                                client,
                                queue_url,
                                items_only,
                                send_single=_send_single_fifo_message,
                            )
                            for j, r in enumerate(batch_out):
                                out.append((chunk[j][0], r))
                        return out

                tasks = [run_group(v) for v in buckets.values()]
                group_results = await asyncio.gather(*tasks)
        except IngestUnavailableError:
            raise
        except Exception as exc:  # pragma: no cover - provider failure mapping
            raise IngestUnavailableError(str(exc)) from exc

        flat: list[tuple[int, IngestPutResult]] = []
        for gr in group_results:
            flat.extend(gr)
        flat.sort(key=lambda t: t[0])
        return [r for _, r in flat]


async def _send_fifo_batch(
    client: Any,
    queue_url: str,
    chunk: list[IngestPutInput],
    *,
    send_single: Callable[..., Awaitable[str | None]],
) -> list[IngestPutResult]:
    batch = _build_batch_entries(chunk)
    delay = SQS_SEND_BASE_DELAY_SEC
    response: dict[str, Any] | None = None
    for attempt in range(SQS_SEND_MAX_ATTEMPTS):
        try:
            response = await client.send_message_batch(
                QueueUrl=queue_url,
                Entries=batch,
            )
            break
        except ClientError as exc:
            if not _is_sqs_transient_error(exc) or attempt == SQS_SEND_MAX_ATTEMPTS - 1:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, SQS_SEND_MAX_DELAY_SEC)
    assert response is not None
    message_id_by_idx: dict[int, str | None] = {}
    for row in response.get("Successful", []):
        message_id_by_idx[int(row["Id"])] = (
            str(row["MessageId"]) if row.get("MessageId") else None
        )
    for fail in response.get("Failed", []):
        idx = int(fail["Id"])
        item = chunk[idx]
        mid = await send_single(client, queue_url, item)
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
    delay = SQS_SEND_BASE_DELAY_SEC
    resp: dict[str, Any] | None = None
    for attempt in range(SQS_SEND_MAX_ATTEMPTS):
        try:
            resp = await client.send_message(
                QueueUrl=queue_url,
                MessageBody=body,
                MessageGroupId=partition_key_for_shard(item.shard_id),
                MessageDeduplicationId=_deduplication_id(item.idempotency_key),
            )
            break
        except ClientError as exc:
            if not _is_sqs_transient_error(exc) or attempt == SQS_SEND_MAX_ATTEMPTS - 1:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, SQS_SEND_MAX_DELAY_SEC)
    assert resp is not None
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
