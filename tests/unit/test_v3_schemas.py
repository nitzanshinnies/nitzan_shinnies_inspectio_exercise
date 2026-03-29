"""P0: BulkIntentV1 / SendUnitV1 Pydantic envelopes (master plan §4.4)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from inspectio.v3.schemas.bulk_intent import BulkIntentV1
from inspectio.v3.schemas.send_unit import SendUnitV1


@pytest.mark.unit
def test_bulk_intent_json_round_trip_by_alias() -> None:
    payload = {
        "schemaVersion": 1,
        "traceId": "trace-abc",
        "batchCorrelationId": "batch-xyz",
        "idempotencyKey": "idem-1",
        "count": 3,
        "body": "hello",
        "receivedAtMs": 99,
    }
    model = BulkIntentV1.model_validate(payload)
    dumped = model.model_dump(mode="json", by_alias=True)
    again = BulkIntentV1.model_validate(dumped)
    assert again == model
    assert dumped["schemaVersion"] == 1
    assert dumped["receivedAtMs"] == 99


@pytest.mark.unit
def test_bulk_intent_rejects_invalid_count() -> None:
    with pytest.raises(ValidationError):
        BulkIntentV1(
            trace_id="t",
            batch_correlation_id="b",
            idempotency_key="i",
            count=0,
            body="x",
            received_at_ms=1,
        )


@pytest.mark.unit
def test_send_unit_json_round_trip_by_alias() -> None:
    mid = str(uuid.uuid4())
    payload = {
        "schemaVersion": 1,
        "traceId": "trace-send",
        "messageId": mid,
        "body": "sms body",
        "receivedAtMs": 100,
        "batchCorrelationId": "batch-1",
        "shard": 2,
        "attemptsCompleted": 0,
    }
    model = SendUnitV1.model_validate(payload)
    dumped = model.model_dump(mode="json", by_alias=True)
    again = SendUnitV1.model_validate(dumped)
    assert again == model


@pytest.mark.unit
def test_send_unit_attempts_completed_defaults_to_zero() -> None:
    mid = str(uuid.uuid4())
    model = SendUnitV1(
        trace_id="t",
        message_id=mid,
        body="b",
        received_at_ms=1,
        batch_correlation_id="c",
        shard=0,
    )
    assert model.attempts_completed == 0


@pytest.mark.unit
def test_bulk_intent_optional_metadata_round_trip() -> None:
    model = BulkIntentV1(
        trace_id="t",
        batch_correlation_id="b",
        idempotency_key="k",
        count=1,
        body="x",
        received_at_ms=0,
        metadata={"k": "v"},
    )
    dumped = model.model_dump(mode="json", by_alias=True)
    restored = BulkIntentV1.model_validate(dumped)
    assert restored.metadata == {"k": "v"}
