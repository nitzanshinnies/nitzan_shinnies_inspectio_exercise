"""P2 journal codec tests (TC-JNL-001–005, §18.1–18.2, §28.8)."""

from __future__ import annotations

import gzip
import json

import pytest

from inspectio.journal.records import (
    JournalDecodeError,
    JournalRecordIndexError,
    JournalRecordV1,
    JournalValidationError,
    decode_line,
    encode_line,
    parse_gzip_ndjson_segment,
    validate_monotonic_record_index,
)

BASE = {
    "shardId": 7,
    "messageId": "m-1",
    "tsMs": 1_700_000_000_000,
    "recordIndex": 100,
}


def _line(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


@pytest.mark.unit
def test_tc_jnl_001_round_trip_encode_decode_per_type_required_payload_keys() -> None:
    cases: list[dict] = [
        {
            **BASE,
            "type": "INGEST_APPLIED",
            "payload": {
                "receivedAtMs": 1,
                "idempotencyKey": "k",
                "bodyHash": "a" * 64,
            },
        },
        {
            **BASE,
            "recordIndex": 101,
            "type": "DISPATCH_SCHEDULED",
            "payload": {"reason": "immediate"},
        },
        {
            **BASE,
            "recordIndex": 102,
            "type": "SEND_ATTEMPTED",
            "payload": {"attemptIndex": 0},
        },
        {
            **BASE,
            "recordIndex": 103,
            "type": "SEND_RESULT",
            "payload": {
                "attemptIndex": 0,
                "ok": True,
                "httpStatus": 200,
                "errorClass": None,
            },
        },
        {
            **BASE,
            "recordIndex": 104,
            "type": "NEXT_DUE",
            "payload": {"attemptCount": 1, "nextDueAtMs": 1_700_000_000_500},
        },
        {
            **BASE,
            "recordIndex": 105,
            "type": "TERMINAL",
            "payload": {"status": "success", "attemptCount": 1},
        },
        {
            **BASE,
            "recordIndex": 106,
            "type": "TERMINAL",
            "payload": {"status": "failed", "attemptCount": 6, "reason": "timeout"},
        },
    ]
    for wire in cases:
        wire = {**wire, "v": 1}
        line = _line(wire)
        rec = decode_line(line)
        out = encode_line(rec)
        assert json.loads(out) == json.loads(line)


@pytest.mark.unit
def test_tc_jnl_002_decode_rejects_missing_or_wrong_v() -> None:
    good = {
        **BASE,
        "v": 1,
        "type": "TERMINAL",
        "payload": {"status": "success", "attemptCount": 1},
    }
    decode_line(_line(good))

    bad_missing = {k: v for k, v in good.items() if k != "v"}
    with pytest.raises(JournalDecodeError):
        decode_line(_line(bad_missing))

    bad_version = {**good, "v": 2}
    with pytest.raises(JournalDecodeError):
        decode_line(_line(bad_version))


@pytest.mark.unit
def test_tc_jnl_003_terminal_failed_requires_reason_before_write() -> None:
    bad = {
        **BASE,
        "v": 1,
        "type": "TERMINAL",
        "payload": {"status": "failed", "attemptCount": 6},
    }
    with pytest.raises(JournalValidationError):
        decode_line(_line(bad))

    rec = JournalRecordV1.model_validate(
        {
            **bad,
            "payload": {"status": "failed", "attemptCount": 6, "reason": "x"},
        }
    )
    encode_line(rec)


@pytest.mark.unit
def test_tc_jnl_004_rejects_non_monotonic_record_index_per_shard() -> None:
    first = {
        **BASE,
        "v": 1,
        "type": "TERMINAL",
        "recordIndex": 5,
        "payload": {"status": "success", "attemptCount": 1},
    }
    r1 = decode_line(_line(first))
    validate_monotonic_record_index(None, r1)
    validate_monotonic_record_index(4, r1)

    second = {**first, "recordIndex": 4}
    r2 = decode_line(_line(second))
    with pytest.raises(JournalRecordIndexError):
        validate_monotonic_record_index(5, r2)


@pytest.mark.unit
def test_tc_jnl_005_ndjson_two_lines_and_gzip_round_trip() -> None:
    a = {
        **BASE,
        "v": 1,
        "type": "TERMINAL",
        "recordIndex": 1,
        "payload": {"status": "success", "attemptCount": 1},
    }
    b = {**a, "recordIndex": 2, "messageId": "m-2"}
    ndjson = _line(a) + "\n" + _line(b) + "\n"
    records = parse_gzip_ndjson_segment(gzip.compress(ndjson.encode("utf-8")))
    assert len(records) == 2
    assert records[0].record_index == 1
    assert records[1].record_index == 2

    raw = gzip.compress(ndjson.encode("utf-8"))
    assert parse_gzip_ndjson_segment(raw) == parse_gzip_ndjson_segment(
        gzip.compress(gzip.decompress(raw))
    )
