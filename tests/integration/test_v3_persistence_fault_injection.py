"""P12.6: persistence correctness under fault-injection scenarios."""

from __future__ import annotations

from typing import Any

import pytest

from inspectio.v3.domain.retry_schedule import attempt_deadline_ms
from inspectio.v3.persistence_recovery.bootstrap import PersistenceRecoveryBootstrap
from inspectio.v3.persistence_recovery.order import sorted_for_replay
from inspectio.v3.persistence_recovery.reducer import fold_event
from inspectio.v3.persistence_writer.writer import (
    BufferedPersistenceWriter,
    PersistenceWriterFlushError,
)
from inspectio.v3.schemas.persistence_event import (
    EVENT_TYPE_ATTEMPT_RESULT,
    EVENT_TYPE_TERMINAL,
    PersistenceEventV1,
)

_RECEIVED_AT_MS = 10_000
_SHARD_ZERO = 0


class _FaultStore:
    def __init__(self) -> None:
        self.bytes: dict[str, bytes] = {}
        self.jsons: dict[str, dict[str, Any]] = {}
        self.fail_put_json_once = False
        self.fail_put_bytes_once = False
        self.put_bytes_calls = 0
        self.put_json_calls = 0

    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        content_encoding: str | None = None,
    ) -> None:
        _ = (content_type, content_encoding)
        self.put_bytes_calls += 1
        if self.fail_put_bytes_once:
            self.fail_put_bytes_once = False
            raise RuntimeError("temporary s3 bytes failure")
        self.bytes[key] = data

    async def put_json(self, *, key: str, data: dict[str, Any]) -> None:
        self.put_json_calls += 1
        if self.fail_put_json_once:
            self.fail_put_json_once = False
            raise RuntimeError("checkpoint write failure")
        self.jsons[key] = data

    async def get_json(self, *, key: str) -> dict[str, Any] | None:
        return self.jsons.get(key)

    async def get_bytes(self, *, key: str) -> bytes | None:
        return self.bytes.get(key)

    async def list_keys(self, *, prefix: str) -> list[str]:
        return sorted(key for key in self.bytes if key.startswith(prefix))


def _writer(
    *,
    store: _FaultStore,
    now_ms: int,
    write_max_attempts: int = 3,
) -> BufferedPersistenceWriter:
    return BufferedPersistenceWriter(
        store=store,
        clock_ms=lambda: now_ms,
        flush_max_events=500,
        flush_min_batch_events=1,
        flush_interval_ms=1_000,
        dedupe_event_id_cap=200_000,
        write_max_attempts=write_max_attempts,
        backoff_base_ms=1,
        backoff_max_ms=2,
        backoff_jitter_fraction=0.0,
    )


def _event(
    *,
    event_id: str,
    event_type: str,
    message_id: str,
    shard: int,
    segment_seq: int,
    segment_event_index: int,
    attempt_count: int,
    status: str,
    next_due_at_ms: int | None,
) -> PersistenceEventV1:
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "eventId": event_id,
        "eventType": event_type,
        "emittedAtMs": 1_700_000_000_000 + segment_seq * 10 + segment_event_index,
        "shard": shard,
        "segmentSeq": segment_seq,
        "segmentEventIndex": segment_event_index,
        "traceId": f"trace-{message_id}",
        "batchCorrelationId": f"batch-{message_id}",
        "messageId": message_id,
        "attemptCount": attempt_count,
        "status": status,
        "receivedAtMs": _RECEIVED_AT_MS,
        "body": f"body-{message_id}",
    }
    if event_type == EVENT_TYPE_ATTEMPT_RESULT:
        payload["attemptOk"] = status == "success"
        payload["nextDueAtMs"] = next_due_at_ms
    if event_type == EVENT_TYPE_TERMINAL:
        payload["finalTimestampMs"] = _RECEIVED_AT_MS + 1_000
        if status == "failed":
            payload["reason"] = "max_try_send_failures"
    return PersistenceEventV1.model_validate(payload)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crash_between_emission_and_transport_ack_no_pending_loss() -> None:
    store = _FaultStore()
    event = _event(
        event_id="evt-1",
        event_type=EVENT_TYPE_ATTEMPT_RESULT,
        message_id="m-1",
        shard=_SHARD_ZERO,
        segment_seq=11,
        segment_event_index=0,
        attempt_count=1,
        status="pending",
        next_due_at_ms=attempt_deadline_ms(_RECEIVED_AT_MS, 2),
    )

    writer_a = _writer(store=store, now_ms=20_000)
    await writer_a.ingest_events([event])
    await writer_a.flush_due(force=True)

    # Simulate crash before upstream ack: event is redelivered on restart.
    writer_b = _writer(store=store, now_ms=21_000)
    await writer_b.ingest_events([event])
    before_bytes = len(store.bytes)
    before_cp = dict(store.jsons["state/checkpoints/0/latest.json"])
    acked = await writer_b.flush_due(force=True)
    assert len(acked) == 1
    assert len(store.bytes) == before_bytes
    assert dict(store.jsons["state/checkpoints/0/latest.json"]) == before_cp
    assert writer_b.metrics.events_dropped_committed_watermark == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_crash_after_segment_write_before_checkpoint_update_recovers() -> None:
    store = _FaultStore()
    store.fail_put_json_once = True
    event = _event(
        event_id="evt-2",
        event_type=EVENT_TYPE_ATTEMPT_RESULT,
        message_id="m-2",
        shard=_SHARD_ZERO,
        segment_seq=12,
        segment_event_index=0,
        attempt_count=1,
        status="pending",
        next_due_at_ms=attempt_deadline_ms(_RECEIVED_AT_MS, 2),
    )

    writer_a = _writer(store=store, now_ms=22_000, write_max_attempts=1)
    await writer_a.ingest_events([event])
    with pytest.raises(PersistenceWriterFlushError):
        await writer_a.flush_due(force=True)

    # Restart + redelivery should converge to durable pending state.
    writer_b = _writer(store=store, now_ms=23_000)
    await writer_b.ingest_events([event])
    acked = await writer_b.flush_due(force=True)
    assert len(acked) == 1
    assert "state/checkpoints/0/latest.json" in store.jsons
    checkpoint = store.jsons["state/checkpoints/0/latest.json"]
    assert checkpoint["committedSourceSegmentSeq"] == 12
    assert checkpoint["committedSourceEventIndex"] == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_transport_delivery_terminal_applies_once_logically() -> None:
    terminal_a = _event(
        event_id="dup-a",
        event_type=EVENT_TYPE_TERMINAL,
        message_id="m-3",
        shard=_SHARD_ZERO,
        segment_seq=13,
        segment_event_index=0,
        attempt_count=6,
        status="failed",
        next_due_at_ms=None,
    )
    terminal_b = _event(
        event_id="dup-b",
        event_type=EVENT_TYPE_TERMINAL,
        message_id="m-3",
        shard=_SHARD_ZERO,
        segment_seq=13,
        segment_event_index=0,
        attempt_count=6,
        status="failed",
        next_due_at_ms=None,
    )
    ordered = sorted_for_replay([terminal_b, terminal_a])
    state = None
    for event in ordered:
        state = fold_event(state, event)
    assert state is not None
    assert state.status == "failed"
    assert state.attempt_count == 6


@pytest.mark.integration
@pytest.mark.asyncio
async def test_out_of_order_delivery_across_shards_replay_is_deterministic() -> None:
    store = _FaultStore()
    writer = _writer(store=store, now_ms=25_000)
    events = [
        _event(
            event_id="s1-late",
            event_type=EVENT_TYPE_ATTEMPT_RESULT,
            message_id="m-4",
            shard=1,
            segment_seq=20,
            segment_event_index=1,
            attempt_count=2,
            status="pending",
            next_due_at_ms=attempt_deadline_ms(_RECEIVED_AT_MS, 3),
        ),
        _event(
            event_id="s0-early",
            event_type=EVENT_TYPE_ATTEMPT_RESULT,
            message_id="m-5",
            shard=0,
            segment_seq=19,
            segment_event_index=0,
            attempt_count=1,
            status="pending",
            next_due_at_ms=attempt_deadline_ms(_RECEIVED_AT_MS, 2),
        ),
    ]
    await writer.ingest_events(events[::-1])
    await writer.flush_due(force=True)
    first = await PersistenceRecoveryBootstrap(
        object_store=store, shard_ids=[0, 1]
    ).recover()
    second = await PersistenceRecoveryBootstrap(
        object_store=store, shard_ids=[0, 1]
    ).recover()
    assert first.pending_units == second.pending_units
    assert first.terminal_message_ids == second.terminal_message_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_temporary_s3_failure_retries_and_recovers() -> None:
    store = _FaultStore()
    store.fail_put_bytes_once = True
    writer = _writer(store=store, now_ms=26_000)
    await writer.ingest_events(
        [
            _event(
                event_id="evt-6",
                event_type=EVENT_TYPE_ATTEMPT_RESULT,
                message_id="m-6",
                shard=_SHARD_ZERO,
                segment_seq=26,
                segment_event_index=0,
                attempt_count=1,
                status="pending",
                next_due_at_ms=attempt_deadline_ms(_RECEIVED_AT_MS, 2),
            )
        ]
    )
    await writer.flush_due(force=True)
    assert writer.metrics.flush_retries >= 1
    assert writer.metrics.segments_written == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_writer_restart_during_high_ingest_converges_without_duplicate_terminals() -> (
    None
):
    store = _FaultStore()
    writer_a = _writer(store=store, now_ms=27_000)
    batch_a: list[PersistenceEventV1] = []
    for idx in range(120):
        batch_a.append(
            _event(
                event_id=f"high-a-{idx}",
                event_type=EVENT_TYPE_ATTEMPT_RESULT,
                message_id=f"m-high-{idx}",
                shard=idx % 2,
                segment_seq=30 + idx // 8,
                segment_event_index=idx % 8,
                attempt_count=1,
                status="pending",
                next_due_at_ms=attempt_deadline_ms(_RECEIVED_AT_MS, 2),
            )
        )
    await writer_a.ingest_events(batch_a)
    await writer_a.flush_due(force=True)

    # Restart with overlap + terminal updates for a subset.
    writer_b = _writer(store=store, now_ms=28_000)
    overlap = batch_a[:50]
    terminal_updates = [
        _event(
            event_id=f"high-term-{idx}",
            event_type=EVENT_TYPE_TERMINAL,
            message_id=f"m-high-{idx}",
            shard=idx % 2,
            segment_seq=80 + idx // 8,
            segment_event_index=idx % 8,
            attempt_count=6,
            status="failed",
            next_due_at_ms=None,
        )
        for idx in range(25)
    ]
    await writer_b.ingest_events(overlap + terminal_updates)
    await writer_b.flush_due(force=True)
    assert writer_b.metrics.events_dropped_committed_watermark == 50
    assert writer_b.metrics.events_flushed == 25
    cp0 = store.jsons["state/checkpoints/0/latest.json"]
    cp1 = store.jsons["state/checkpoints/1/latest.json"]
    assert cp0["committedSourceSegmentSeq"] >= 80
    assert cp1["committedSourceSegmentSeq"] >= 80
