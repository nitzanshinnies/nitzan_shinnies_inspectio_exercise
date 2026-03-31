"""P12.3: buffered writer segment/checkpoint behavior."""

from __future__ import annotations

import gzip
import json
from collections.abc import Sequence
from typing import Any

import pytest

from inspectio.v3.persistence_writer.writer import (
    BufferedPersistenceWriter,
    PersistenceWriterFlushError,
)
from inspectio.v3.schemas.persistence_event import PersistenceEventV1


def _event(
    event_id: str,
    *,
    shard: int = 0,
    emitted_at_ms: int = 100,
    segment_seq: int = 1,
    segment_event_index: int = 0,
) -> PersistenceEventV1:
    return PersistenceEventV1.model_validate(
        {
            "schemaVersion": 1,
            "eventId": event_id,
            "eventType": "attempt_result",
            "emittedAtMs": emitted_at_ms,
            "shard": shard,
            "segmentSeq": segment_seq,
            "segmentEventIndex": segment_event_index,
            "traceId": "t",
            "batchCorrelationId": "b",
            "messageId": "m",
            "receivedAtMs": 99,
            "attemptCount": 1,
            "attemptOk": True,
            "status": "pending",
            "nextDueAtMs": 120,
        },
    )


class _MemStore:
    def __init__(self) -> None:
        self.bytes: dict[str, bytes] = {}
        self.jsons: dict[str, dict[str, Any]] = {}
        self.fail_checkpoint_once = False
        self.fail_put_bytes_once = False
        self.put_bytes_calls = 0

    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        content_encoding: str | None = None,
    ) -> None:
        self.put_bytes_calls += 1
        if self.fail_put_bytes_once:
            self.fail_put_bytes_once = False
            raise RuntimeError("segment write fail")
        self.bytes[key] = data

    async def put_json(self, *, key: str, data: dict[str, Any]) -> None:
        if self.fail_checkpoint_once:
            self.fail_checkpoint_once = False
            raise RuntimeError("checkpoint fail")
        self.jsons[key] = data

    async def get_json(self, *, key: str) -> dict[str, Any] | None:
        return self.jsons.get(key)


def _decode_segment(data: bytes) -> list[dict[str, Any]]:
    raw = gzip.decompress(data).decode("utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _build_writer(
    store: _MemStore,
    *,
    clock: list[int],
    flush_max_events: int = 100,
    flush_interval_ms: int = 1_000,
) -> BufferedPersistenceWriter:
    return BufferedPersistenceWriter(
        store=store,
        clock_ms=lambda: clock[0],
        flush_max_events=flush_max_events,
        flush_interval_ms=flush_interval_ms,
        dedupe_event_id_cap=1_000,
        write_max_attempts=2,
        backoff_base_ms=1,
        backoff_max_ms=1,
        backoff_jitter_fraction=0.0,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_writer_batches_events_into_one_segment_per_flush() -> None:
    store = _MemStore()
    clock = [10_000]
    writer = _build_writer(
        store, clock=clock, flush_max_events=100, flush_interval_ms=1_000
    )
    events: Sequence[PersistenceEventV1] = [
        _event(f"e-{i}", emitted_at_ms=9_000 + i) for i in range(5)
    ]
    await writer.ingest_events(events)
    flushed = await writer.flush_due(force=True)

    assert len(flushed) == 5
    assert writer.metrics.segments_written == 1
    assert writer.metrics.events_flushed == 5
    key = "state/events/0/00000000000000000000.ndjson.gz"
    assert key in store.bytes
    decoded = _decode_segment(store.bytes[key])
    assert len(decoded) == 5
    cp = store.jsons["state/checkpoints/0/latest.json"]
    assert cp["lastSegmentSeq"] == 0
    assert cp["nextSegmentSeq"] == 1
    assert cp["committedSourceSegmentSeq"] == 1
    assert cp["committedSourceEventIndex"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_writer_segment_before_checkpoint_contract_retryable() -> None:
    store = _MemStore()
    store.fail_checkpoint_once = True
    clock = [20_000]
    writer = _build_writer(store, clock=clock)
    await writer.ingest_events([_event("e-1"), _event("e-2")])
    flushed = await writer.flush_due(force=True)
    assert len(flushed) == 2
    assert (
        store.put_bytes_calls >= 2
    )  # overwrite same segment key after checkpoint failure
    cp = store.jsons["state/checkpoints/0/latest.json"]
    assert cp["segmentObjectKey"] == "state/events/0/00000000000000000000.ndjson.gz"
    assert writer.metrics.checkpoint_write_retries >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_writer_segment_put_retry_increments_s3_put_retries() -> None:
    store = _MemStore()
    store.fail_put_bytes_once = True
    clock = [20_500]
    writer = _build_writer(store, clock=clock)
    await writer.ingest_events([_event("e-seg-retry")])
    flushed = await writer.flush_due(force=True)
    assert len(flushed) == 1
    assert writer.metrics.s3_put_retries >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_writer_exhausted_failures_raise_and_buffer_remains() -> None:
    store = _MemStore()
    store.fail_checkpoint_once = True
    clock = [30_000]
    writer = BufferedPersistenceWriter(
        store=store,
        clock_ms=lambda: clock[0],
        flush_max_events=1,
        flush_interval_ms=1,
        dedupe_event_id_cap=100,
        write_max_attempts=1,
        backoff_base_ms=1,
        backoff_max_ms=1,
        backoff_jitter_fraction=0.0,
    )
    await writer.ingest_events([_event("e-3")])
    with pytest.raises(PersistenceWriterFlushError):
        await writer.flush_due(force=True)
    assert writer.metrics.flush_failures == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_writer_dedupes_duplicate_event_ids() -> None:
    store = _MemStore()
    clock = [40_000]
    writer = _build_writer(store, clock=clock)
    e = _event("dup-1")
    await writer.ingest_events([e, e])
    await writer.flush_due(force=True)
    assert writer.metrics.events_deduped == 1
    assert writer.metrics.events_flushed == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_restart_redelivery_drop_by_committed_watermark_no_new_segment() -> None:
    store = _MemStore()
    clock = [50_000]
    writer1 = _build_writer(store, clock=clock)
    batch_a = [
        _event("a-1", segment_seq=11, segment_event_index=0),
        _event("a-2", segment_seq=11, segment_event_index=1),
    ]
    await writer1.ingest_events(batch_a)
    acked_a = await writer1.flush_due(force=True)
    assert len(acked_a) == 2
    assert writer1.metrics.segments_written == 1
    assert (
        store.jsons["state/checkpoints/0/latest.json"]["committedSourceSegmentSeq"]
        == 11
    )
    assert (
        store.jsons["state/checkpoints/0/latest.json"]["committedSourceEventIndex"] == 1
    )

    # Restart with same durable store/checkpoint, then redeliver already-committed events.
    writer2 = _build_writer(store, clock=clock)
    await writer2.ingest_events(batch_a)
    before_bytes = len(store.bytes)
    before_cp = dict(store.jsons["state/checkpoints/0/latest.json"])
    acked_redelivered = await writer2.flush_due(force=True)
    after_bytes = len(store.bytes)
    after_cp = dict(store.jsons["state/checkpoints/0/latest.json"])
    assert len(acked_redelivered) == 2
    assert after_bytes == before_bytes
    assert after_cp == before_cp
    assert writer2.metrics.events_dropped_committed_watermark == 2
    assert writer2.metrics.empty_flushes_due_to_dedupe == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mixed_batch_filters_committed_events_and_advances_checkpoint() -> None:
    store = _MemStore()
    clock = [60_000]
    writer1 = _build_writer(store, clock=clock)
    await writer1.ingest_events(
        [
            _event("b-1", segment_seq=21, segment_event_index=0),
            _event("b-2", segment_seq=21, segment_event_index=1),
        ],
    )
    await writer1.flush_due(force=True)

    writer2 = _build_writer(store, clock=clock)
    mixed = [
        _event("b-1-redelivered", segment_seq=21, segment_event_index=0),
        _event("c-1-new", segment_seq=22, segment_event_index=0),
        _event("c-2-new", segment_seq=22, segment_event_index=1),
    ]
    await writer2.ingest_events(mixed)
    acked = await writer2.flush_due(force=True)
    assert len(acked) == 3
    cp = store.jsons["state/checkpoints/0/latest.json"]
    assert cp["committedSourceSegmentSeq"] == 22
    assert cp["committedSourceEventIndex"] == 1
    assert writer2.metrics.events_dropped_committed_watermark == 1
    assert writer2.metrics.events_flushed == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_backward_compat_old_checkpoint_payload_loads_safely() -> None:
    store = _MemStore()
    store.jsons["state/checkpoints/0/latest.json"] = {
        "schemaVersion": 1,
        "shard": 0,
        "lastSegmentSeq": 4,
        "nextSegmentSeq": 5,
        "lastEventIndex": 8,
        "updatedAtMs": 100,
        "segmentObjectKey": "state/events/0/00000000000000000004.ndjson.gz",
    }
    clock = [70_000]
    writer = _build_writer(store, clock=clock)
    await writer.ingest_events([_event("d-1", segment_seq=1, segment_event_index=0)])
    acked = await writer.flush_due(force=True)
    assert len(acked) == 1
    cp = store.jsons["state/checkpoints/0/latest.json"]
    assert cp["lastSegmentSeq"] == 5
    assert cp["nextSegmentSeq"] == 6


@pytest.mark.unit
@pytest.mark.asyncio
async def test_writer_metrics_snapshot_contains_per_shard_fields() -> None:
    store = _MemStore()
    clock = [80_000]
    writer = _build_writer(
        store, clock=clock, flush_max_events=2, flush_interval_ms=10_000
    )
    await writer.ingest_events([_event("obs-1", shard=0), _event("obs-2", shard=0)])
    await writer.flush_due(force=True)
    writer.metrics.observe_ack_batch(shard=0, events=2, latency_ms=7, now_ms=clock[0])
    snapshot = writer.metrics.snapshot(now_ms=clock[0] + 1000)
    shard = snapshot["shards"]["0"]
    assert "receive_events_total" in shard
    assert "flush_payload_bytes_last" in shard
    assert "ack_latency_ms_last" in shard
    assert "buffered_events" in shard
