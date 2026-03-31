"""P12.3: end-to-end fake flow (consumer -> writer -> ack)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from inspectio.v3.persistence_writer.writer import BufferedPersistenceWriter
from inspectio.v3.schemas.persistence_event import PersistenceEventV1


def _event(event_id: str, *, shard: int) -> PersistenceEventV1:
    return PersistenceEventV1.model_validate(
        {
            "schemaVersion": 1,
            "eventId": event_id,
            "eventType": "terminal",
            "emittedAtMs": 1_700_000_000_000,
            "shard": shard,
            "segmentSeq": int(event_id.split("-")[-1]),
            "segmentEventIndex": 0,
            "traceId": "t",
            "batchCorrelationId": "b",
            "messageId": f"m-{event_id}",
            "receivedAtMs": 1_700_000_000_000,
            "attemptCount": 1,
            "status": "success",
            "finalTimestampMs": 1_700_000_000_001,
        },
    )


class _MemStore:
    def __init__(self) -> None:
        self.bytes: dict[str, bytes] = {}
        self.jsons: dict[str, dict[str, Any]] = {}

    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        content_encoding: str | None = None,
    ) -> None:
        self.bytes[key] = data

    async def put_json(self, *, key: str, data: dict[str, Any]) -> None:
        self.jsons[key] = data

    async def get_json(self, *, key: str) -> dict[str, Any] | None:
        return self.jsons.get(key)


class _FakeConsumer:
    def __init__(self, events: Sequence[PersistenceEventV1]) -> None:
        self._events = list(events)
        self.acked: list[str] = []

    async def receive_many(self, *, max_events: int) -> list[PersistenceEventV1]:
        if not self._events:
            return []
        chunk = self._events[:max_events]
        self._events = self._events[max_events:]
        return chunk

    async def ack_many(self, events: Sequence[PersistenceEventV1]) -> None:
        self.acked.extend([e.event_id for e in events])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fake_flow_flushes_and_acks_consumed_events() -> None:
    events = [_event(f"e-{i}", shard=i % 2) for i in range(20)]
    consumer = _FakeConsumer(events)
    store = _MemStore()
    clock = [1_700_000_100_000]
    writer = BufferedPersistenceWriter(
        store=store,
        clock_ms=lambda: clock[0],
        flush_max_events=8,
        flush_interval_ms=10_000,
        dedupe_event_id_cap=10_000,
        write_max_attempts=2,
        backoff_base_ms=1,
        backoff_max_ms=1,
        backoff_jitter_fraction=0.0,
    )
    while True:
        batch = await consumer.receive_many(max_events=10)
        if not batch:
            break
        await writer.ingest_events(batch)
        flushed = await writer.flush_due(force=False)
        if flushed:
            await consumer.ack_many(flushed)
    flushed_tail = await writer.flush_due(force=True)
    if flushed_tail:
        await consumer.ack_many(flushed_tail)

    assert len(consumer.acked) == 20
    assert writer.metrics.segments_written >= 2
    assert "state/checkpoints/0/latest.json" in store.jsons
    assert "state/checkpoints/1/latest.json" in store.jsons


@pytest.mark.integration
@pytest.mark.asyncio
async def test_writer_restart_redelivery_idempotent() -> None:
    store = _MemStore()
    clock = [1_700_000_200_000]
    writer_a = BufferedPersistenceWriter(
        store=store,
        clock_ms=lambda: clock[0],
        flush_max_events=10,
        flush_interval_ms=10_000,
        dedupe_event_id_cap=10_000,
        write_max_attempts=2,
        backoff_base_ms=1,
        backoff_max_ms=1,
        backoff_jitter_fraction=0.0,
    )
    batch_a = [_event("a-100", shard=0), _event("a-101", shard=0)]
    await writer_a.ingest_events(batch_a)
    acked_a = await writer_a.flush_due(force=True)
    assert len(acked_a) == 2
    cp_before = dict(store.jsons["state/checkpoints/0/latest.json"])
    bytes_before = dict(store.bytes)

    # restart + redelivery of already committed events
    writer_b = BufferedPersistenceWriter(
        store=store,
        clock_ms=lambda: clock[0],
        flush_max_events=10,
        flush_interval_ms=10_000,
        dedupe_event_id_cap=10_000,
        write_max_attempts=2,
        backoff_base_ms=1,
        backoff_max_ms=1,
        backoff_jitter_fraction=0.0,
    )
    await writer_b.ingest_events(batch_a)
    acked_redelivery = await writer_b.flush_due(force=True)
    assert len(acked_redelivery) == 2
    assert dict(store.jsons["state/checkpoints/0/latest.json"]) == cp_before
    assert dict(store.bytes) == bytes_before
    assert writer_b.metrics.events_dropped_committed_watermark == 2
