"""P2 ingest schema tests (ingest stream contract)."""

from __future__ import annotations

import hashlib

import pytest

from inspectio.ingest.schema import (
    MessageIngestPayload,
    MessageIngestedV1,
    body_hash_for_text,
)

BODY = "hello world"
MID = "123e4567-e89b-12d3-a456-426614174000"


@pytest.mark.unit
def test_body_hash_is_lowercase_hex_sha256_utf8_payload_body() -> None:
    expected = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    assert body_hash_for_text(BODY) == expected
    assert body_hash_for_text(BODY) == expected.lower()


@pytest.mark.unit
def test_message_ingested_v1_round_trip_includes_matching_body_hash() -> None:
    record = MessageIngestedV1(
        message_id=MID,
        payload=MessageIngestPayload(body=BODY, to="+15550000000"),
        received_at_ms=1_700_000_000_000,
        shard_id=42,
        idempotency_key=MID,
    )
    assert record.body_hash == body_hash_for_text(BODY)

    raw = record.to_json_dict()
    assert raw["schema"] == "MessageIngestedV1"
    assert raw["bodyHash"] == record.body_hash
    assert raw["payload"]["body"] == BODY

    restored = MessageIngestedV1.from_json_dict(raw)
    assert restored == record


@pytest.mark.unit
def test_message_ingested_v1_rejects_wrong_body_hash() -> None:
    record = MessageIngestedV1(
        message_id=MID,
        payload=MessageIngestPayload(body=BODY),
        received_at_ms=1,
        shard_id=0,
        idempotency_key=MID,
    )
    raw = record.to_json_dict()
    raw["bodyHash"] = "0" * 64
    with pytest.raises(ValueError):
        MessageIngestedV1.from_json_dict(raw)
