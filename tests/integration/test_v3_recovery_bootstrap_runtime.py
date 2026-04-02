"""P12.4: runtime recovery bootstrap integration coverage."""

from __future__ import annotations

import gzip
import json
from typing import Any

import pytest

from inspectio.v3.domain.retry_schedule import attempt_deadline_ms
from inspectio.v3.persistence_recovery.bootstrap import PersistenceRecoveryBootstrap
from inspectio.v3.schemas.persistence_event import (
    EVENT_TYPE_ATTEMPT_RESULT,
    EVENT_TYPE_TERMINAL,
    PersistenceEventV1,
)
from inspectio.v3.worker.metrics import SendWorkerMetrics
from inspectio.v3.worker.scheduler import SendScheduler


class _InstrumentedStore:
    def __init__(self) -> None:
        self.jsons: dict[str, dict[str, Any]] = {}
        self.bytes: dict[str, bytes] = {}
        self.get_json_calls = 0
        self.get_bytes_calls = 0
        self.list_keys_calls = 0

    async def put_json(self, *, key: str, data: dict[str, Any]) -> None:
        self.jsons[key] = data

    async def get_json(self, *, key: str) -> dict[str, Any] | None:
        self.get_json_calls += 1
        return self.jsons.get(key)

    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        content_encoding: str | None = None,
    ) -> None:
        _ = (content_type, content_encoding)
        self.bytes[key] = data

    async def get_bytes(self, *, key: str) -> bytes | None:
        self.get_bytes_calls += 1
        return self.bytes.get(key)

    async def list_keys(self, *, prefix: str) -> list[str]:
        self.list_keys_calls += 1
        return sorted(key for key in self.bytes if key.startswith(prefix))


class _MemOutcomes:
    def __init__(self) -> None:
        self.success: list[str] = []
        self.failed: list[str] = []

    async def record_success(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
    ) -> None:
        _ = (attempt_count, final_timestamp_ms)
        self.success.append(message_id)

    async def record_failed(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
        reason: str,
    ) -> None:
        _ = (attempt_count, final_timestamp_ms, reason)
        self.failed.append(message_id)


def _event(
    *,
    event_type: str,
    event_id: str,
    message_id: str,
    attempt_count: int,
    status: str,
    next_due_at_ms: int | None,
    segment_event_index: int,
    body: str,
    reason: str | None = None,
) -> PersistenceEventV1:
    return PersistenceEventV1.model_validate(
        {
            "schemaVersion": 1,
            "eventId": event_id,
            "eventType": event_type,
            "emittedAtMs": 1_700_000_000_000 + segment_event_index,
            "shard": 0,
            "segmentSeq": 0,
            "segmentEventIndex": segment_event_index,
            "traceId": "trace-1",
            "batchCorrelationId": "batch-1",
            "messageId": message_id,
            "attemptCount": attempt_count,
            "attemptOk": status == "success",
            "status": status,
            "nextDueAtMs": next_due_at_ms,
            "receivedAtMs": 10_000,
            "body": body,
            "finalTimestampMs": 11_000 if event_type == EVENT_TYPE_TERMINAL else None,
            "reason": reason,
        },
    )


async def _write_segment(
    store: _InstrumentedStore,
    *,
    key: str,
    events: list[PersistenceEventV1],
) -> None:
    payload = "\n".join(
        json.dumps(event.model_dump(mode="json", by_alias=True, exclude_none=True))
        for event in events
    )
    await store.put_bytes(
        key=key,
        data=gzip.compress((payload + "\n").encode("utf-8")),
        content_type="application/x-ndjson",
        content_encoding="gzip",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crash_restart_recovery_no_pending_loss_runtime_path() -> None:
    store = _InstrumentedStore()
    await _write_segment(
        store,
        key="state/events/0/00000000000000000000.ndjson.gz",
        events=[
            _event(
                event_type=EVENT_TYPE_ATTEMPT_RESULT,
                event_id="evt-pending",
                message_id="m-pending",
                attempt_count=1,
                status="pending",
                next_due_at_ms=attempt_deadline_ms(10_000, 2),
                segment_event_index=0,
                body="body-pending",
            ),
            _event(
                event_type=EVENT_TYPE_TERMINAL,
                event_id="evt-terminal",
                message_id="m-terminal",
                attempt_count=1,
                status="success",
                next_due_at_ms=None,
                segment_event_index=1,
                body="body-terminal",
            ),
        ],
    )

    snapshot = await PersistenceRecoveryBootstrap(
        object_store=store, shard_ids=[0]
    ).recover()
    outcomes = _MemOutcomes()
    processed: list[str] = []
    deleted_receipts: list[str] = []
    now = [11_000]

    async def delete_message(receipt_handle: str) -> None:
        deleted_receipts.append(receipt_handle)

    scheduler = SendScheduler(
        clock_ms=lambda: now[0],
        try_send=lambda message: processed.append(message.message_id) or True,
        outcomes=outcomes,
        delete_sqs_message=delete_message,
        metrics=SendWorkerMetrics(),
    )
    scheduler.seed_recovered_terminal_ids(snapshot.terminal_message_ids)
    scheduler.seed_recovered_pending(snapshot.pending_units)

    await scheduler.wakeup_scan_due()
    await scheduler.wakeup_scan_due()

    assert processed == ["m-pending"]
    assert outcomes.success == ["m-pending"]
    assert outcomes.failed == []
    assert deleted_receipts == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_recovery_restart_determinism_same_snapshot() -> None:
    store = _InstrumentedStore()
    await _write_segment(
        store,
        key="state/events/0/00000000000000000000.ndjson.gz",
        events=[
            _event(
                event_type=EVENT_TYPE_ATTEMPT_RESULT,
                event_id="evt-1",
                message_id="m-1",
                attempt_count=1,
                status="pending",
                next_due_at_ms=attempt_deadline_ms(10_000, 2),
                segment_event_index=0,
                body="body-1",
            ),
        ],
    )

    bootstrap = PersistenceRecoveryBootstrap(object_store=store, shard_ids=[0])
    first = await bootstrap.recover()
    second = await bootstrap.recover()
    assert first == second


@pytest.mark.integration
@pytest.mark.asyncio
async def test_s3_access_happens_only_during_startup_recovery() -> None:
    store = _InstrumentedStore()
    await _write_segment(
        store,
        key="state/events/0/00000000000000000000.ndjson.gz",
        events=[
            _event(
                event_type=EVENT_TYPE_ATTEMPT_RESULT,
                event_id="evt-1",
                message_id="m-1",
                attempt_count=1,
                status="pending",
                next_due_at_ms=attempt_deadline_ms(10_000, 2),
                segment_event_index=0,
                body="body-1",
            ),
        ],
    )

    snapshot = await PersistenceRecoveryBootstrap(
        object_store=store, shard_ids=[0]
    ).recover()
    startup_calls = (
        store.get_json_calls,
        store.list_keys_calls,
        store.get_bytes_calls,
    )

    outcomes = _MemOutcomes()
    scheduler = SendScheduler(
        clock_ms=lambda: 11_000,
        try_send=lambda _message: True,
        outcomes=outcomes,
        delete_sqs_message=lambda _receipt: _async_none(),
        metrics=SendWorkerMetrics(),
    )
    scheduler.seed_recovered_terminal_ids(snapshot.terminal_message_ids)
    scheduler.seed_recovered_pending(snapshot.pending_units)
    await scheduler.wakeup_scan_due()
    await scheduler.wakeup_scan_due()

    assert (
        store.get_json_calls,
        store.list_keys_calls,
        store.get_bytes_calls,
    ) == startup_calls


async def _async_none() -> None:
    return None
