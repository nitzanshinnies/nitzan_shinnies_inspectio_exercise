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
    event_id: str, *, shard: int = 0, emitted_at_ms: int = 100
) -> PersistenceEventV1:
    return PersistenceEventV1.model_validate(
        {
            "schemaVersion": 1,
            "eventId": event_id,
            "eventType": "attempt_result",
            "emittedAtMs": emitted_at_ms,
            "shard": shard,
            "segmentSeq": 1,
            "segmentEventIndex": 0,
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
