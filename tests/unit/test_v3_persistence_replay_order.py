"""P12.0: deterministic replay order and idempotent fold."""

from __future__ import annotations

import uuid

import pytest

from inspectio.v3.persistence_recovery.order import sorted_for_replay
from inspectio.v3.persistence_recovery.reducer import fold_event
from inspectio.v3.schemas.persistence_event import (
    EVENT_TYPE_ATTEMPT_RESULT,
    EVENT_TYPE_ENQUEUED,
    EVENT_TYPE_TERMINAL,
    TERMINAL_STATUS_PENDING,
    TERMINAL_STATUS_SUCCESS,
    PersistenceEventV1,
)


def _event(
    *,
    event_type: str,
    seq: int,
    idx: int,
    event_id: str,
    message_id: str = "m-1",
    attempt_count: int | None = None,
    status: str | None = None,
    attempt_ok: bool | None = None,
    next_due_at_ms: int | None = None,
    final_timestamp_ms: int | None = None,
) -> PersistenceEventV1:
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "eventId": event_id,
        "eventType": event_type,
        "emittedAtMs": 100 + seq * 10 + idx,
        "shard": 0,
        "segmentSeq": seq,
        "segmentEventIndex": idx,
        "traceId": "t-1",
        "batchCorrelationId": "b-1",
        "messageId": message_id,
        "attemptCount": attempt_count,
        "status": status,
        "attemptOk": attempt_ok,
        "nextDueAtMs": next_due_at_ms,
        "finalTimestampMs": final_timestamp_ms,
        "count": 1,
        "body": "hello",
        "receivedAtMs": 100,
    }
    return PersistenceEventV1.model_validate(payload)


@pytest.mark.unit
def test_sorted_for_replay_total_order_stable(
    fake_persistence_transport: object,
) -> None:
    e1 = _event(
        event_type=EVENT_TYPE_ATTEMPT_RESULT,
        seq=9,
        idx=2,
        event_id="e-2",
        attempt_count=1,
        attempt_ok=False,
        next_due_at_ms=600,
        status=TERMINAL_STATUS_PENDING,
    )
    e2 = _event(
        event_type=EVENT_TYPE_ENQUEUED,
        seq=9,
        idx=1,
        event_id="e-1",
        status=TERMINAL_STATUS_PENDING,
        message_id=str(uuid.uuid4()),
    )
    e3 = _event(
        event_type=EVENT_TYPE_TERMINAL,
        seq=10,
        idx=0,
        event_id="e-3",
        attempt_count=2,
        status=TERMINAL_STATUS_SUCCESS,
        final_timestamp_ms=800,
    )

    # Fixture contract for P12.0: fake transport can hold unordered delivery.
    transport = fake_persistence_transport
    transport.publish(e3.model_dump(mode="json", by_alias=True))
    transport.publish(e1.model_dump(mode="json", by_alias=True))
    transport.publish(e2.model_dump(mode="json", by_alias=True))
    unordered = [
        PersistenceEventV1.model_validate(x) for x in transport.drain_unordered(seed=3)
    ]
    ordered = sorted_for_replay(unordered)
    assert [e.event_id for e in ordered] == ["e-1", "e-2", "e-3"]


@pytest.mark.unit
def test_fold_event_terminal_idempotency_and_monotonic_attempt_count(
    deterministic_clock: object,
) -> None:
    clock = deterministic_clock
    events = sorted_for_replay(
        [
            _event(
                event_type=EVENT_TYPE_TERMINAL,
                seq=7,
                idx=1,
                event_id="terminal-1",
                attempt_count=2,
                status=TERMINAL_STATUS_SUCCESS,
                final_timestamp_ms=700,
            ),
            _event(
                event_type=EVENT_TYPE_ATTEMPT_RESULT,
                seq=7,
                idx=0,
                event_id="attempt-1",
                attempt_count=1,
                attempt_ok=True,
                status=TERMINAL_STATUS_PENDING,
            ),
            _event(
                event_type=EVENT_TYPE_TERMINAL,
                seq=7,
                idx=2,
                event_id="terminal-dup",
                attempt_count=2,
                status=TERMINAL_STATUS_SUCCESS,
                final_timestamp_ms=701,
            ),
        ],
    )
    clock.advance_ms(5)
    state = None
    for e in events:
        state = fold_event(state, e)
    assert state is not None
    assert state.attempt_count == 2
    assert state.status == TERMINAL_STATUS_SUCCESS
