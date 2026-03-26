"""P5 stream/consumer tests (TC-STR-001..003, §28.4 item 2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from inspectio.ingest.ingest_consumer import (
    CheckpointStore,
    IngestConsumer,
    IngestRawRecord,
    S3CheckpointStore,
    partition_key_for_shard,
)
from inspectio.ingest.sqs_fifo_consumer import SqsFifoBatchFetcher
from inspectio.ingest.schema import MessageIngestPayload, MessageIngestedV1
from inspectio.journal.records import JournalRecordV1
from inspectio.worker.handlers import IngestJournalHandler


@dataclass(frozen=True, slots=True)
class _CheckpointCall:
    checkpoint_shard_id: str
    sequence_number: str
    updated_at_ms: int


class _FakeCheckpointStore(CheckpointStore):
    def __init__(self, journal: "_FakeJournalWriter") -> None:
        self.calls: list[_CheckpointCall] = []
        self._journal = journal

    async def save(
        self,
        *,
        checkpoint_shard_id: str,
        sequence_number: str,
        updated_at_ms: int,
    ) -> None:
        # §18.3 / §28.4 item 2: checkpoint only after journal durable flush.
        assert self._journal.flushed
        self.calls.append(
            _CheckpointCall(
                checkpoint_shard_id=checkpoint_shard_id,
                sequence_number=sequence_number,
                updated_at_ms=updated_at_ms,
            )
        )


class _FakeJournalWriter:
    def __init__(self) -> None:
        self.records: list[JournalRecordV1] = []
        self.flushed = False

    async def append(self, record: JournalRecordV1) -> None:
        self.records.append(record)
        self.flushed = False

    async def flush(self) -> None:
        self.flushed = True


class _FakeIdempotencyStore:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def set_nx(self, *, key: str, value: str, ttl_sec: int) -> bool:
        _ = value
        _ = ttl_sec
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


class _CaptureS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"ETag": "x"}


def _raw_record(message: MessageIngestedV1, *, sequence: str) -> IngestRawRecord:
    wire = json.dumps(
        message.to_json_dict(), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return IngestRawRecord(
        checkpoint_shard_id="shardId-000000000000",
        sequence_number=sequence,
        data=wire,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tc_str_001_duplicate_ingest_is_deduped() -> None:
    message = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174000",
        payload=MessageIngestPayload(body="hello", to="+15550000000"),
        received_at_ms=1_700_000_000_000,
        shard_id=7,
        idempotency_key="idem-1",
    )
    journal = _FakeJournalWriter()
    consumer = IngestConsumer(
        handler=IngestJournalHandler(
            idempotency_store=_FakeIdempotencyStore(),
            idempotency_ttl_sec=86_400,
        ),
        journal_writer=journal,
        checkpoint_store=_FakeCheckpointStore(journal),
        now_ms=lambda: 1_700_000_000_123,
    )
    await consumer.process_record(_raw_record(message, sequence="1"))
    await consumer.process_record(_raw_record(message, sequence="2"))

    assert [r.type for r in journal.records].count("INGEST_APPLIED") == 1
    assert [r.type for r in journal.records].count("DISPATCH_SCHEDULED") == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tc_str_002_ordered_records_checkpoint_after_each() -> None:
    m1 = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174001",
        payload=MessageIngestPayload(body="a", to="+15550000001"),
        received_at_ms=1_700_000_000_000,
        shard_id=7,
        idempotency_key="idem-a",
    )
    m2 = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174002",
        payload=MessageIngestPayload(body="b", to="+15550000002"),
        received_at_ms=1_700_000_000_001,
        shard_id=7,
        idempotency_key="idem-b",
    )
    journal = _FakeJournalWriter()
    checkpoint = _FakeCheckpointStore(journal)
    consumer = IngestConsumer(
        handler=IngestJournalHandler(
            idempotency_store=_FakeIdempotencyStore(),
            idempotency_ttl_sec=86_400,
        ),
        journal_writer=journal,
        checkpoint_store=checkpoint,
        now_ms=lambda: 1_700_000_000_321,
    )
    await consumer.process_record(_raw_record(m1, sequence="10"))
    await consumer.process_record(_raw_record(m2, sequence="11"))

    assert [c.sequence_number for c in checkpoint.calls] == ["10", "11"]
    assert len(journal.records) == 4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_consume_once_polls_batch_and_processes_all_rows() -> None:
    m1 = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174003",
        payload=MessageIngestPayload(body="a", to="+15550000001"),
        received_at_ms=1_700_000_000_010,
        shard_id=7,
        idempotency_key="idem-c",
    )
    m2 = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174004",
        payload=MessageIngestPayload(body="b", to="+15550000002"),
        received_at_ms=1_700_000_000_020,
        shard_id=7,
        idempotency_key="idem-d",
    )
    journal = _FakeJournalWriter()
    checkpoint = _FakeCheckpointStore(journal)
    consumer = IngestConsumer(
        handler=IngestJournalHandler(
            idempotency_store=_FakeIdempotencyStore(),
            idempotency_ttl_sec=86_400,
        ),
        journal_writer=journal,
        checkpoint_store=checkpoint,
        now_ms=lambda: 1_700_000_000_999,
    )

    async def _fetch_records() -> list[IngestRawRecord]:
        return [_raw_record(m1, sequence="12"), _raw_record(m2, sequence="13")]

    count = await consumer.consume_once(fetch_records=_fetch_records)
    assert count == 2
    assert [c.sequence_number for c in checkpoint.calls] == ["12", "13"]
    assert len(journal.records) == 4


@pytest.mark.integration
def test_tc_str_003_partition_key_format_is_zero_padded_5_digits() -> None:
    assert partition_key_for_shard(0) == "00000"
    assert partition_key_for_shard(42) == "00042"
    assert partition_key_for_shard(1023) == "01023"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_checkpoint_store_uses_section_29_4_s3_key_layout() -> None:
    s3 = _CaptureS3Client()
    store = S3CheckpointStore(
        s3_client=s3,
        bucket="bucket-a",
        stream_name="inspectio-ingest",
        key_prefix="state/checkpoints/kinesis/",
    )
    await store.save(
        checkpoint_shard_id="shardId-000000000000",
        sequence_number="200",
        updated_at_ms=1_700_000_000_444,
    )
    assert len(s3.calls) == 1
    call = s3.calls[0]
    assert call["Bucket"] == "bucket-a"
    assert (
        call["Key"]
        == "state/checkpoints/kinesis/inspectio-ingest/shard-shardId-000000000000.json"
    )
    body = json.loads(bytes(call["Body"]).decode("utf-8"))
    assert body == {"sequenceNumber": "200", "updatedAtMs": 1_700_000_000_444}


def _sqs_message_dict(
    message: MessageIngestedV1, *, mid: str, rh: str
) -> dict[str, Any]:
    body = json.dumps(message.to_json_dict(), separators=(",", ":"), sort_keys=True)
    return {"MessageId": mid, "ReceiptHandle": rh, "Body": body}


class _FakeSqsClient:
    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        self._queue = list(messages or [])
        self.visibility_calls: list[dict[str, Any]] = []

    async def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        if not self._queue:
            return {}
        return {"Messages": [self._queue.pop(0)]}

    async def change_message_visibility(self, **kwargs: Any) -> None:
        self.visibility_calls.append(dict(kwargs))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetcher_polls_sqs_and_maps_owned_logical_shard() -> None:
    message = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174005",
        payload=MessageIngestPayload(body="x", to="+15550000003"),
        received_at_ms=1_700_000_000_111,
        shard_id=7,
        idempotency_key="idem-e",
    )
    fake = _FakeSqsClient(messages=[_sqs_message_dict(message, mid="mid-9", rh="rh-9")])
    fetcher = SqsFifoBatchFetcher(
        sqs_client=fake,
        queue_url="http://example/queue",
        worker_index=0,
        worker_replicas=1,
        total_shards=1024,
        wait_seconds=0,
    )
    rows = await fetcher.fetch_records()
    assert len(rows) == 1
    assert rows[0].sequence_number == "mid-9"
    assert rows[0].sqs_receipt_handle == "rh-9"
    assert not fake.visibility_calls


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetcher_rereleases_message_for_unowned_logical_shard() -> None:
    message = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174099",
        payload=MessageIngestPayload(body="x", to="+15550000003"),
        received_at_ms=1_700_000_000_111,
        shard_id=999,
        idempotency_key="idem-x",
    )
    fake = _FakeSqsClient(messages=[_sqs_message_dict(message, mid="mid-x", rh="rh-x")])
    fetcher = SqsFifoBatchFetcher(
        sqs_client=fake,
        queue_url="http://example/queue",
        worker_index=0,
        worker_replicas=2,
        total_shards=1024,
        wait_seconds=0,
    )
    rows = await fetcher.fetch_records()
    assert rows == []
    assert len(fake.visibility_calls) == 1
    assert fake.visibility_calls[0]["VisibilityTimeout"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetcher_worker_one_owns_high_shard_range() -> None:
    message = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174099",
        payload=MessageIngestPayload(body="x", to="+15550000003"),
        received_at_ms=1_700_000_000_111,
        shard_id=999,
        idempotency_key="idem-x",
    )
    fake = _FakeSqsClient(messages=[_sqs_message_dict(message, mid="mid-x", rh="rh-x")])
    fetcher = SqsFifoBatchFetcher(
        sqs_client=fake,
        queue_url="http://example/queue",
        worker_index=1,
        worker_replicas=2,
        total_shards=1024,
        wait_seconds=0,
    )
    rows = await fetcher.fetch_records()
    assert len(rows) == 1
    assert rows[0].sqs_receipt_handle == "rh-x"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_process_record_sqs_deletes_after_journal() -> None:
    message = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174005",
        payload=MessageIngestPayload(body="x", to="+15550000003"),
        received_at_ms=1_700_000_000_111,
        shard_id=7,
        idempotency_key="idem-sqs",
    )
    wire = json.dumps(
        message.to_json_dict(), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    deleted: list[str] = []

    async def _delete(rh: str) -> None:
        deleted.append(rh)

    journal = _FakeJournalWriter()
    consumer = IngestConsumer(
        handler=IngestJournalHandler(
            idempotency_store=_FakeIdempotencyStore(),
            idempotency_ttl_sec=86_400,
        ),
        journal_writer=journal,
        checkpoint_store=None,
        sqs_delete=_delete,
        now_ms=lambda: 1_700_000_000_555,
    )
    await consumer.process_record(
        IngestRawRecord(
            checkpoint_shard_id="mid-1",
            sequence_number="mid-1",
            data=wire,
            sqs_receipt_handle="rh-abc",
        )
    )
    assert deleted == ["rh-abc"]
