"""P12.4: worker recovery bootstrap from persisted segments."""

from __future__ import annotations

import gzip
import json

import pytest

from inspectio.v3.persistence_recovery.bootstrap import PersistenceRecoveryBootstrap
from inspectio.v3.schemas.persistence_event import (
    EVENT_TYPE_ATTEMPT_RESULT,
    EVENT_TYPE_TERMINAL,
    PersistenceEventV1,
)


class _MemStore:
    def __init__(self) -> None:
        self._json: dict[str, dict[str, object]] = {}
        self._bytes: dict[str, bytes] = {}

    async def put_json(self, *, key: str, data: dict[str, object]) -> None:
        self._json[key] = data

    async def get_json(self, *, key: str) -> dict[str, object] | None:
        return self._json.get(key)

    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str,
        content_encoding: str | None = None,
    ) -> None:
        _ = (content_type, content_encoding)
        self._bytes[key] = data

    async def get_bytes(self, *, key: str) -> bytes | None:
        return self._bytes.get(key)

    async def list_keys(self, *, prefix: str) -> list[str]:
        return sorted(k for k in self._bytes if k.startswith(prefix))


def _event(
    *,
    event_type: str,
    event_id: str,
    message_id: str,
    segment_seq: int,
    segment_event_index: int,
    attempt_count: int,
    status: str,
    next_due_at_ms: int | None,
    body: str | None,
) -> PersistenceEventV1:
    return PersistenceEventV1.model_validate(
        {
            "schemaVersion": 1,
            "eventId": event_id,
            "eventType": event_type,
            "emittedAtMs": 1000 + segment_seq * 10 + segment_event_index,
            "shard": 0,
            "segmentSeq": segment_seq,
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
        }
    )


async def _write_segment(
    store: _MemStore, *, key: str, events: list[PersistenceEventV1]
) -> None:
    payload = "\n".join(
        json.dumps(e.model_dump(mode="json", by_alias=True, exclude_none=True))
        for e in events
    )
    await store.put_bytes(
        key=key,
        data=gzip.compress((payload + "\n").encode("utf-8")),
        content_type="application/x-ndjson",
        content_encoding="gzip",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recovery_bootstrap_rebuilds_pending_and_terminal_sets() -> None:
    store = _MemStore()
    await store.put_json(
        key="state/checkpoints/0/latest.json",
        data={
            "schemaVersion": 1,
            "shard": 0,
            "lastSegmentSeq": 0,
            "nextSegmentSeq": 1,
            "lastEventIndex": 1,
            "committedSourceSegmentSeq": 0,
            "committedSourceEventIndex": 1,
            "updatedAtMs": 12_000,
            "segmentObjectKey": "state/events/0/00000000000000000000.ndjson.gz",
        },
    )
    await _write_segment(
        store,
        key="state/events/0/00000000000000000000.ndjson.gz",
        events=[
            _event(
                event_type=EVENT_TYPE_ATTEMPT_RESULT,
                event_id="evt-a1",
                message_id="m-pending",
                segment_seq=0,
                segment_event_index=0,
                attempt_count=1,
                status="pending",
                next_due_at_ms=10_500,
                body="hello",
            ),
            _event(
                event_type=EVENT_TYPE_TERMINAL,
                event_id="evt-t1",
                message_id="m-terminal",
                segment_seq=0,
                segment_event_index=1,
                attempt_count=1,
                status="success",
                next_due_at_ms=None,
                body="done",
            ),
        ],
    )

    bootstrap = PersistenceRecoveryBootstrap(object_store=store, shard_ids=[0])
    snapshot = await bootstrap.recover()

    assert snapshot.loaded_segments == 1
    assert snapshot.loaded_events == 2
    assert snapshot.terminal_message_ids == {"m-terminal"}
    assert len(snapshot.pending_units) == 1
    pending = snapshot.pending_units[0]
    assert pending.message_id == "m-pending"
    assert pending.attempt_count == 1
    assert pending.next_due_at_ms == 10_500
    assert pending.body == "hello"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recovery_bootstrap_is_deterministic_across_repeated_runs() -> None:
    store = _MemStore()
    await _write_segment(
        store,
        key="state/events/0/00000000000000000001.ndjson.gz",
        events=[
            _event(
                event_type=EVENT_TYPE_ATTEMPT_RESULT,
                event_id="evt-2",
                message_id="m-1",
                segment_seq=1,
                segment_event_index=1,
                attempt_count=2,
                status="pending",
                next_due_at_ms=11_000,
                body=None,
            ),
            _event(
                event_type=EVENT_TYPE_ATTEMPT_RESULT,
                event_id="evt-1",
                message_id="m-1",
                segment_seq=1,
                segment_event_index=0,
                attempt_count=1,
                status="pending",
                next_due_at_ms=10_500,
                body="payload",
            ),
        ],
    )

    bootstrap = PersistenceRecoveryBootstrap(object_store=store, shard_ids=[0])
    first = await bootstrap.recover()
    second = await bootstrap.recover()

    assert first.pending_units == second.pending_units
    assert first.terminal_message_ids == second.terminal_message_ids
    assert first.skipped_pending_missing_body == 0
