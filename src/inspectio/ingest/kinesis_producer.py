"""Kinesis producer for API admission path (§17, P3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import aioboto3

from inspectio.ingest.schema import MessageIngestPayload, MessageIngestedV1
from inspectio.settings import Settings

MAX_PUT_RECORDS_BATCH = 500
PARTITION_KEY_WIDTH = 5


class IngestUnavailableError(RuntimeError):
    """Raised when ingest stream is unavailable."""


class IngestBufferOverflowError(RuntimeError):
    """Raised when in-memory ingest policy must reject requests."""


@dataclass(frozen=True, slots=True)
class IngestPutInput:
    """Input row for a Kinesis ingest write."""

    idempotency_key: str
    message_id: str
    payload_body: str
    payload_to: str
    received_at_ms: int
    shard_id: int


@dataclass(frozen=True, slots=True)
class IngestPutResult:
    """Per-message write result returned to route layer."""

    message_id: str
    shard_id: int
    ingest_sequence: str | None


class IngestProducer(Protocol):
    """Route-facing producer contract for dependency injection."""

    async def put_messages(
        self, messages: list[IngestPutInput]
    ) -> list[IngestPutResult]:
        """Write one or more ingest records and return per-record result."""


class KinesisIngestProducer:
    """AWS Kinesis PutRecords implementation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def put_messages(
        self, messages: list[IngestPutInput]
    ) -> list[IngestPutResult]:
        if len(messages) > MAX_PUT_RECORDS_BATCH:
            msg = f"max batch size is {MAX_PUT_RECORDS_BATCH}"
            raise ValueError(msg)

        records = [_to_put_record(item) for item in messages]
        try:
            session = aioboto3.Session()
            async with session.client(
                "kinesis", region_name=self._settings.inspectio_aws_region
            ) as client:
                response = await client.put_records(
                    StreamName=self._settings.inspectio_kinesis_stream_name,
                    Records=records,
                )
        except Exception as exc:  # pragma: no cover - provider failure mapping
            raise IngestUnavailableError(str(exc)) from exc

        out: list[IngestPutResult] = []
        response_rows = response.get("Records", [])
        for idx, item in enumerate(messages):
            seq = _extract_sequence(response_rows, idx)
            out.append(
                IngestPutResult(
                    message_id=item.message_id,
                    shard_id=item.shard_id,
                    ingest_sequence=seq,
                )
            )
        return out


def _extract_sequence(response_rows: list[dict[str, Any]], idx: int) -> str | None:
    if idx >= len(response_rows):
        return None
    row = response_rows[idx]
    if "ErrorCode" in row:
        raise IngestUnavailableError(str(row.get("ErrorCode")))
    sequence = row.get("SequenceNumber")
    if sequence is None:
        return None
    return str(sequence)


def _to_put_record(item: IngestPutInput) -> dict[str, Any]:
    value = MessageIngestedV1(
        message_id=item.message_id,
        payload=MessageIngestPayload(body=item.payload_body, to=item.payload_to),
        received_at_ms=item.received_at_ms,
        shard_id=item.shard_id,
        idempotency_key=item.idempotency_key,
    ).to_json_dict()
    data = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return {
        "Data": data,
        "PartitionKey": f"{item.shard_id:0{PARTITION_KEY_WIDTH}d}",
    }
