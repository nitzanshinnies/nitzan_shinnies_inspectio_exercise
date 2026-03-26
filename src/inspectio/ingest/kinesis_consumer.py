"""Kinesis ingest consumer for P5 (dedupe + journal + checkpoint ordering)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

from inspectio.ingest.schema import MessageIngestedV1
from inspectio.journal.records import JournalRecordV1
from inspectio.worker.handlers import IngestJournalHandler

PARTITION_KEY_WIDTH = 5


def partition_key_for_shard(shard_id: int) -> str:
    """Return producer/stream-compatible zero-padded partition key (TC-STR-003)."""
    return f"{shard_id:0{PARTITION_KEY_WIDTH}d}"


@dataclass(frozen=True, slots=True)
class KinesisRawRecord:
    """Minimal decoded Kinesis row used by consumer tests/runtime."""

    kinesis_shard_id: str
    sequence_number: str
    data: bytes


class JournalWriter(Protocol):
    """Minimal writer protocol needed by P5 ingest path."""

    async def append(self, record: JournalRecordV1) -> None:
        """Buffer one journal line."""

    async def flush(self) -> None:
        """Durably flush buffered lines."""


class CheckpointStore(Protocol):
    """Checkpoint persistence interface (S3 in production)."""

    async def save(
        self,
        *,
        kinesis_shard_id: str,
        sequence_number: str,
        updated_at_ms: int,
    ) -> None:
        """Persist post-journal checkpoint."""


class KinesisIngestConsumer:
    """Process Kinesis ingest rows in §18.3 order: journal before checkpoint."""

    def __init__(
        self,
        *,
        handler: IngestJournalHandler,
        journal_writer: JournalWriter,
        checkpoint_store: CheckpointStore,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._handler = handler
        self._journal_writer = journal_writer
        self._checkpoint_store = checkpoint_store
        self._now_ms = now_ms or _default_now_ms
        self._last_record_index_by_shard: dict[int, int] = {}

    async def process_record(self, row: KinesisRawRecord) -> None:
        wire = json.loads(row.data.decode("utf-8"))
        message = MessageIngestedV1.from_json_dict(wire)
        journal_lines = await self._handler.apply_ingest(
            message=message,
            next_record_index=lambda: self._next_record_index(message.shard_id),
            now_ms=self._now_ms(),
        )
        for line in journal_lines:
            await self._journal_writer.append(line)
        if journal_lines:
            await self._journal_writer.flush()
        await self._checkpoint_store.save(
            kinesis_shard_id=row.kinesis_shard_id,
            sequence_number=row.sequence_number,
            updated_at_ms=self._now_ms(),
        )

    async def consume_once(
        self,
        *,
        fetch_records: Callable[[], Awaitable[list[KinesisRawRecord]]],
    ) -> int:
        """Poll and process one batch from Kinesis (single-worker friendly path)."""
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
    """S3 checkpoint implementation using §29.4 key + JSON shape."""

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
        kinesis_shard_id: str,
        sequence_number: str,
        updated_at_ms: int,
    ) -> None:
        key = f"{self._key_prefix}{self._stream_name}/shard-{kinesis_shard_id}.json"
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


class KinesisClient(Protocol):
    """Minimal async Kinesis client protocol for polling."""

    async def list_shards(self, **kwargs: Any) -> dict[str, Any]:
        """List shards for stream."""

    async def get_shard_iterator(self, **kwargs: Any) -> dict[str, Any]:
        """Get shard iterator for reads."""

    async def get_records(self, **kwargs: Any) -> dict[str, Any]:
        """Fetch records for shard iterator."""


class KinesisBatchFetcher:
    """Single-worker shard poller for one stream (§29.6)."""

    def __init__(
        self,
        *,
        kinesis_client: KinesisClient,
        stream_name: str,
        max_records_per_shard: int = 1000,
    ) -> None:
        self._kinesis_client = kinesis_client
        self._stream_name = stream_name
        self._max_records_per_shard = max_records_per_shard
        self._iterators_by_shard_id: dict[str, str] = {}

    async def fetch_records(self) -> list[KinesisRawRecord]:
        """Poll each shard once and return all rows found in this pass."""
        shard_ids = await self._list_shard_ids()
        rows: list[KinesisRawRecord] = []
        for shard_id in shard_ids:
            iterator = await self._get_or_create_iterator(shard_id)
            if iterator is None:
                continue
            response = await self._kinesis_client.get_records(
                ShardIterator=iterator,
                Limit=self._max_records_per_shard,
            )
            next_iterator = response.get("NextShardIterator")
            if next_iterator:
                self._iterators_by_shard_id[shard_id] = str(next_iterator)
            records = response.get("Records", [])
            for item in records:
                data = bytes(item["Data"])
                rows.append(
                    KinesisRawRecord(
                        kinesis_shard_id=shard_id,
                        sequence_number=str(item["SequenceNumber"]),
                        data=data,
                    )
                )
        return rows

    async def _list_shard_ids(self) -> list[str]:
        response = await self._kinesis_client.list_shards(StreamName=self._stream_name)
        shards = response.get("Shards", [])
        return [str(item["ShardId"]) for item in shards]

    async def _get_or_create_iterator(self, shard_id: str) -> str | None:
        existing = self._iterators_by_shard_id.get(shard_id)
        if existing is not None:
            return existing
        response = await self._kinesis_client.get_shard_iterator(
            StreamName=self._stream_name,
            ShardId=shard_id,
            ShardIteratorType="TRIM_HORIZON",
        )
        iterator = response.get("ShardIterator")
        if iterator is None:
            return None
        iterator_str = str(iterator)
        self._iterators_by_shard_id[shard_id] = iterator_str
        return iterator_str
