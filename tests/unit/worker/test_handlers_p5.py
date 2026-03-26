"""P5 handler tests (journal template A and synthetic replay baseline)."""

from __future__ import annotations

import pytest

from inspectio.ingest.schema import MessageIngestPayload, MessageIngestedV1
from inspectio.journal.records import JournalRecordV1
from inspectio.models import Message
from inspectio.worker.handlers import (
    IngestJournalHandler,
    replay_pending_from_journal_lines,
)
from inspectio.worker.runtime import InMemorySchedulerRuntime


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handler_emits_template_a_records_for_new_ingest() -> None:
    handler = IngestJournalHandler(
        idempotency_store=_FakeIdempotencyStore(),
        idempotency_ttl_sec=86_400,
    )
    message = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174010",
        payload=MessageIngestPayload(body="hello", to="+15550000000"),
        received_at_ms=1_700_000_000_000,
        shard_id=7,
        idempotency_key="idem-z",
    )
    records = await handler.apply_ingest(
        message=message,
        next_record_index=lambda: 100,
        now_ms=1_700_000_000_001,
    )
    assert [r.type for r in records] == ["INGEST_APPLIED", "DISPATCH_SCHEDULED"]
    assert records[0].payload["idempotencyKey"] == "idem-z"
    assert records[0].payload["bodyHash"] == message.body_hash
    assert records[1].payload["reason"] == "immediate"


@pytest.mark.unit
def test_tc_rec_001_synthetic_replay_rebuilds_pending_state() -> None:
    lines = [
        JournalRecordV1.model_validate(
            {
                "v": 1,
                "type": "INGEST_APPLIED",
                "shardId": 7,
                "messageId": "m-1",
                "tsMs": 1_700_000_000_000,
                "recordIndex": 1,
                "payload": {
                    "receivedAtMs": 1_700_000_000_000,
                    "idempotencyKey": "m-1",
                    "bodyHash": "a" * 64,
                },
            }
        ),
        JournalRecordV1.model_validate(
            {
                "v": 1,
                "type": "DISPATCH_SCHEDULED",
                "shardId": 7,
                "messageId": "m-1",
                "tsMs": 1_700_000_000_001,
                "recordIndex": 2,
                "payload": {"reason": "immediate"},
            }
        ),
    ]
    rebuilt = replay_pending_from_journal_lines(lines)
    assert rebuilt["m-1"]["attemptCount"] == 0
    assert rebuilt["m-1"]["nextDueAtMs"] == 1_700_000_000_000


class _AlwaysSuccessSender:
    async def send(self, message: Message, attempt_index: int) -> bool:
        _ = message
        _ = attempt_index
        return True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handler_reindexes_runtime_records_from_next_record_index() -> None:
    runtime = InMemorySchedulerRuntime(
        now_ms=lambda: 1_700_000_000_100,
        sms_sender=_AlwaysSuccessSender(),
    )
    handler = IngestJournalHandler(
        idempotency_store=_FakeIdempotencyStore(),
        idempotency_ttl_sec=86_400,
        runtime=runtime,
    )
    message = MessageIngestedV1(
        message_id="123e4567-e89b-12d3-a456-426614174011",
        payload=MessageIngestPayload(body="hello", to="+15550000001"),
        received_at_ms=1_700_000_000_000,
        shard_id=7,
        idempotency_key="idem-y",
    )
    next_index = 40

    def _next_record_index() -> int:
        nonlocal next_index
        next_index += 1
        return next_index

    records = await handler.apply_ingest(
        message=message,
        next_record_index=_next_record_index,
        now_ms=1_700_000_000_101,
    )

    assert [record.record_index for record in records] == [41, 42, 43, 44, 45]
    assert [record.record_index for record in runtime.journal] == [43, 44, 45]
