"""P12.0: persistence event/checkpoint strict schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from inspectio.v3.schemas.persistence_checkpoint import PersistenceCheckpointV1
from inspectio.v3.schemas.persistence_event import (
    EVENT_TYPE_ATTEMPT_RESULT,
    EVENT_TYPE_ENQUEUED,
    EVENT_TYPE_TERMINAL,
    TERMINAL_STATUS_FAILED,
    TERMINAL_STATUS_SUCCESS,
    PersistenceEventV1,
)


def _base() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "eventId": "e-1",
        "emittedAtMs": 100,
        "shard": 0,
        "segmentSeq": 10,
        "segmentEventIndex": 2,
        "traceId": "trace-1",
        "batchCorrelationId": "batch-1",
    }


@pytest.mark.unit
def test_enqueued_event_round_trip() -> None:
    payload = {
        **_base(),
        "eventType": EVENT_TYPE_ENQUEUED,
        "count": 3,
        "body": "hello",
        "receivedAtMs": 99,
        "status": "pending",
    }
    model = PersistenceEventV1.model_validate(payload)
    dumped = model.model_dump(mode="json", by_alias=True)
    assert PersistenceEventV1.model_validate(dumped) == model


@pytest.mark.unit
def test_attempt_result_requires_message_and_attempt() -> None:
    payload = {
        **_base(),
        "eventType": EVENT_TYPE_ATTEMPT_RESULT,
        "attemptOk": True,
    }
    with pytest.raises(ValidationError):
        PersistenceEventV1.model_validate(payload)


@pytest.mark.unit
def test_terminal_requires_status_and_reason_for_failed() -> None:
    ok_payload = {
        **_base(),
        "eventType": EVENT_TYPE_TERMINAL,
        "messageId": "m-1",
        "attemptCount": 2,
        "status": TERMINAL_STATUS_SUCCESS,
        "finalTimestampMs": 200,
    }
    ok_model = PersistenceEventV1.model_validate(ok_payload)
    assert ok_model.status == TERMINAL_STATUS_SUCCESS

    bad_payload = {
        **_base(),
        "eventType": EVENT_TYPE_TERMINAL,
        "messageId": "m-1",
        "attemptCount": 6,
        "status": TERMINAL_STATUS_FAILED,
        "finalTimestampMs": 500,
    }
    with pytest.raises(ValidationError):
        PersistenceEventV1.model_validate(bad_payload)


@pytest.mark.unit
def test_checkpoint_requires_next_seq_minus_last_seq_one() -> None:
    payload = {
        "schemaVersion": 1,
        "shard": 0,
        "lastSegmentSeq": 10,
        "nextSegmentSeq": 11,
        "lastEventIndex": 9,
        "updatedAtMs": 222,
        "segmentObjectKey": "state/events/0/10.ndjson.gz",
    }
    model = PersistenceCheckpointV1.model_validate(payload)
    dumped = model.model_dump(mode="json", by_alias=True)
    assert PersistenceCheckpointV1.model_validate(dumped) == model

    payload_bad = dict(payload)
    payload_bad["nextSegmentSeq"] = 12
    with pytest.raises(ValidationError):
        PersistenceCheckpointV1.model_validate(payload_bad)


@pytest.mark.unit
def test_checkpoint_backward_compat_without_committed_source_fields() -> None:
    payload = {
        "schemaVersion": 1,
        "shard": 0,
        "lastSegmentSeq": 7,
        "nextSegmentSeq": 8,
        "lastEventIndex": 4,
        "updatedAtMs": 222,
        "segmentObjectKey": "state/events/0/7.ndjson.gz",
    }
    cp = PersistenceCheckpointV1.model_validate(payload)
    assert cp.committed_source_segment_seq == -1
    assert cp.committed_source_event_index == -1
