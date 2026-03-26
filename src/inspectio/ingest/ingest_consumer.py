"""Ingest consumer for P5 (dedupe + journal + commit ordering, §18.3)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from inspectio.ingest.ingest_producer import partition_key_for_shard
from inspectio.ingest.schema import MessageIngestedV1
from inspectio.journal.records import JournalRecordV1
from inspectio.worker.handlers import IngestJournalHandler

__all__ = [
    "CheckpointStore",
    "IngestConsumer",
    "IngestRawRecord",
    "JournalWriter",
    "S3CheckpointStore",
    "partition_key_for_shard",
]


@dataclass(frozen=True, slots=True)
class IngestRawRecord:
    """Decoded ingest row (SQS or legacy checkpoint tests)."""

    checkpoint_shard_id: str
    sequence_number: str
    data: bytes
    sqs_receipt_handle: str | None = None


class JournalWriter(Protocol):
    """Minimal writer protocol needed by P5 ingest path."""

    async def append(self, record: JournalRecordV1) -> None:
        """Buffer one journal line."""

    async def flush(self) -> None:
        """Durably flush buffered lines."""


class CheckpointStore(Protocol):
    """Checkpoint persistence (S3); unused when commit is SQS DeleteMessage."""

    async def save(
        self,
        *,
        checkpoint_shard_id: str,
        sequence_number: str,
        updated_at_ms: int,
    ) -> None:
        """Persist post-journal checkpoint."""


class IngestConsumer:
    """Process ingest rows in §18.3 order: journal before checkpoint/delete."""

    def __init__(
        self,
        *,
        handler: IngestJournalHandler,
        journal_writer: JournalWriter,
        checkpoint_store: CheckpointStore | None,
        sqs_delete: Callable[[str], Awaitable[None]] | None = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._handler = handler
        self._journal_writer = journal_writer
        self._checkpoint_store = checkpoint_store
        self._sqs_delete = sqs_delete
        self._now_ms = now_ms or _default_now_ms
        self._last_record_index_by_shard: dict[int, int] = {}

    async def process_record(self, row: IngestRawRecord) -> None:
        start_ns = time.monotonic_ns()
        wire = json.loads(row.data.decode("utf-8"))
        decode_ns = time.monotonic_ns()
        message = MessageIngestedV1.from_json_dict(wire)
        handler_start_ns = time.monotonic_ns()
        journal_lines = await self._handler.apply_ingest(
            message=message,
            next_record_index=lambda: self._next_record_index(message.shard_id),
            now_ms=self._now_ms(),
        )
        handler_end_ns = time.monotonic_ns()
        for line in journal_lines:
            await self._journal_writer.append(line)
        journal_flush_ns: int | None = None
        if journal_lines:
            await self._journal_writer.flush()
            journal_flush_ns = time.monotonic_ns()
        if row.sqs_receipt_handle is not None:
            if self._sqs_delete is None:
                msg = "sqs_delete is required when sqs_receipt_handle is set"
                raise ValueError(msg)
            sqs_delete_start_ns = time.monotonic_ns()
            await self._sqs_delete(row.sqs_receipt_handle)
            sqs_delete_end_ns = time.monotonic_ns()
            end_ns = time.monotonic_ns()
            journal_ms = (
                (journal_flush_ns - handler_end_ns) / 1_000_000
                if journal_flush_ns is not None
                else 0.0
            )
            print(
                "[inspectio-perf] component=ingest_consumer "
                f"shard_id={message.shard_id} "
                f"decode_ms={(decode_ns - start_ns) / 1_000_000:.3f} "
                f"handler_ms={(handler_end_ns - handler_start_ns) / 1_000_000:.3f} "
                f"journal_ms={journal_ms:.3f} "
                f"sqs_delete_ms={(sqs_delete_end_ns - sqs_delete_start_ns) / 1_000_000:.3f} "
                f"total_ms={(end_ns - start_ns) / 1_000_000:.3f}"
            )
            return
        if self._checkpoint_store is None:
            msg = "checkpoint_store is required when not using SQS receipt handles"
            raise ValueError(msg)
        ckpt_start_ns = time.monotonic_ns()
        await self._checkpoint_store.save(
            checkpoint_shard_id=row.checkpoint_shard_id,
            sequence_number=row.sequence_number,
            updated_at_ms=self._now_ms(),
        )
        ckpt_end_ns = time.monotonic_ns()
        end_ns = time.monotonic_ns()
        journal_ms = (
            (journal_flush_ns - handler_end_ns) / 1_000_000
            if journal_flush_ns is not None
            else 0.0
        )
        print(
            "[inspectio-perf] component=ingest_consumer "
            f"shard_id={message.shard_id} "
            f"decode_ms={(decode_ns - start_ns) / 1_000_000:.3f} "
            f"handler_ms={(handler_end_ns - handler_start_ns) / 1_000_000:.3f} "
            f"journal_ms={journal_ms:.3f} "
            f"checkpoint_ms={(ckpt_end_ns - ckpt_start_ns) / 1_000_000:.3f} "
            f"total_ms={(end_ns - start_ns) / 1_000_000:.3f}"
        )

    async def consume_once(
        self,
        *,
        fetch_records: Callable[[], Awaitable[list[IngestRawRecord]]],
    ) -> int:
        """Poll and process one batch from the ingest queue."""
        rows = await fetch_records()
        for row in rows:
            await self.process_record(row)
        return len(rows)

    def _next_record_index(self, shard_id: int) -> int:
        current = self._last_record_index_by_shard.get(shard_id, 0)
        next_value = current + 1
        self._last_record_index_by_shard[shard_id] = next_value
        return next_value


def _default_now_ms() -> int:
    return int(time.time() * 1000)


class S3CheckpointStore:
    """S3 checkpoint implementation using §29.4-style key + JSON shape."""

    def __init__(
        self,
        *,
        s3_client: Any,
        bucket: str,
        stream_name: str,
        key_prefix: str,
    ) -> None:
        self._s3_client = s3_client
        self._bucket = bucket
        self._stream_name = stream_name
        self._key_prefix = key_prefix

    async def save(
        self,
        *,
        checkpoint_shard_id: str,
        sequence_number: str,
        updated_at_ms: int,
    ) -> None:
        key = f"{self._key_prefix}{self._stream_name}/shard-{checkpoint_shard_id}.json"
        body = json.dumps(
            {"sequenceNumber": sequence_number, "updatedAtMs": updated_at_ms},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        await self._s3_client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
        )
