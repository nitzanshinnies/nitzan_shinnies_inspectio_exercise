"""P12.0: fake durability path integration test (no external services)."""

from __future__ import annotations

import pytest

from inspectio.v3.persistence_recovery.order import sorted_for_replay
from inspectio.v3.persistence_recovery.reducer import fold_event
from inspectio.v3.schemas.persistence_event import (
    EVENT_TYPE_ATTEMPT_RESULT,
    EVENT_TYPE_ENQUEUED,
    EVENT_TYPE_TERMINAL,
    TERMINAL_STATUS_FAILED,
    TERMINAL_STATUS_PENDING,
    PersistenceEventV1,
)


def _evt(
    *,
    event_type: str,
    seq: int,
    idx: int,
    attempt_count: int | None,
    status: str | None,
    attempt_ok: bool | None,
    next_due_at_ms: int | None = None,
    final_timestamp_ms: int | None = None,
) -> PersistenceEventV1:
    return PersistenceEventV1.model_validate(
        {
            "schemaVersion": 1,
            "eventId": f"e-{seq}-{idx}",
            "eventType": event_type,
            "emittedAtMs": 1_700_000_000_000 + seq * 10 + idx,
            "shard": 0,
            "segmentSeq": seq,
            "segmentEventIndex": idx,
            "traceId": "trace",
            "batchCorrelationId": "batch",
            "messageId": "m-1",
            "attemptCount": attempt_count,
            "status": status,
            "reason": "max_try_send_failures"
            if status == TERMINAL_STATUS_FAILED
            else None,
            "count": 1,
            "body": "hello",
            "receivedAtMs": 1_700_000_000_000,
            "attemptOk": attempt_ok,
            "nextDueAtMs": next_due_at_ms,
            "finalTimestampMs": final_timestamp_ms,
        },
    )


@pytest.mark.integration
def test_fake_transport_unordered_delivery_reduces_to_stable_terminal() -> None:
    published = [
        _evt(
            event_type=EVENT_TYPE_ATTEMPT_RESULT,
            seq=9,
            idx=1,
            attempt_count=1,
            status=TERMINAL_STATUS_PENDING,
            attempt_ok=False,
            next_due_at_ms=1_700_000_000_500,
        ),
        _evt(
            event_type=EVENT_TYPE_ENQUEUED,
            seq=9,
            idx=0,
            attempt_count=0,
            status=TERMINAL_STATUS_PENDING,
            attempt_ok=None,
        ),
        _evt(
            event_type=EVENT_TYPE_TERMINAL,
            seq=10,
            idx=0,
            attempt_count=6,
            status=TERMINAL_STATUS_FAILED,
            attempt_ok=False,
            final_timestamp_ms=1_700_000_001_000,
        ),
    ]
    unordered = [published[2], published[0], published[1]]
    ordered = sorted_for_replay(unordered)

    state = None
    for event in ordered:
        state = fold_event(state, event)

    assert state is not None
    assert state.status == TERMINAL_STATUS_FAILED
    assert state.attempt_count == 6
