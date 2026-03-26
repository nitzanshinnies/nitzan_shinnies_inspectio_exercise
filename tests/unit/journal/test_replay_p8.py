"""P8 replay tests (TC-REC-002/003) for snapshot + tail semantics."""

from __future__ import annotations

import gzip
import json

import pytest

from inspectio.journal.replay import (
    SnapshotReplayError,
    apply_tail_records,
    load_snapshot_json,
)


def _record(
    *,
    record_index: int,
    message_id: str,
    record_type: str,
    payload: dict,
) -> str:
    obj = {
        "v": 1,
        "type": record_type,
        "shardId": 7,
        "messageId": message_id,
        "tsMs": 1_700_000_000_000 + record_index,
        "recordIndex": record_index,
        "payload": payload,
    }
    return json.dumps(obj, separators=(",", ":"), sort_keys=True)


@pytest.mark.unit
def test_tc_rec_002_replay_applies_only_tail_record_index_gt_snapshot() -> None:
    snapshot = load_snapshot_json(
        json.dumps(
            {
                "v": 1,
                "shardId": 7,
                "capturedAtMs": 1_700_000_000_000,
                "lastRecordIndex": 100,
                "active": {
                    "m-keep": {
                        "messageId": "m-keep",
                        "attemptCount": 2,
                        "nextDueAtMs": 1_700_000_000_900,
                        "status": "pending",
                        "lastError": None,
                        "payload": {"to": "+1", "body": "hello"},
                    }
                },
                "terminalsIncluded": False,
            }
        )
    )
    # <=100 should be ignored, >100 should apply.
    ndjson = (
        "\n".join(
            [
                _record(
                    record_index=100,
                    message_id="m-ignored",
                    record_type="DISPATCH_SCHEDULED",
                    payload={"reason": "tick"},
                ),
                _record(
                    record_index=101,
                    message_id="m-new",
                    record_type="INGEST_APPLIED",
                    payload={
                        "receivedAtMs": 1_700_000_000_101,
                        "idempotencyKey": "m-new",
                        "bodyHash": "a" * 64,
                    },
                ),
                _record(
                    record_index=102,
                    message_id="m-new",
                    record_type="NEXT_DUE",
                    payload={"attemptCount": 1, "nextDueAtMs": 1_700_000_001_000},
                ),
            ]
        )
        + "\n"
    )
    state = apply_tail_records(
        snapshot=snapshot,
        gzip_segments=[gzip.compress(ndjson.encode("utf-8"))],
    )
    assert "m-keep" in state.active
    assert "m-new" in state.active
    assert "m-ignored" not in state.active
    assert state.active["m-new"]["attemptCount"] == 1
    assert state.last_record_index == 102


@pytest.mark.unit
def test_tc_rec_003_truncated_gzip_raises_and_not_silent_corruption() -> None:
    snapshot = load_snapshot_json(
        json.dumps(
            {
                "v": 1,
                "shardId": 7,
                "capturedAtMs": 1_700_000_000_000,
                "lastRecordIndex": 0,
                "active": {},
                "terminalsIncluded": False,
            }
        )
    )
    good = gzip.compress(
        (
            _record(
                record_index=1,
                message_id="m-1",
                record_type="INGEST_APPLIED",
                payload={
                    "receivedAtMs": 1,
                    "idempotencyKey": "m-1",
                    "bodyHash": "a" * 64,
                },
            )
            + "\n"
        ).encode("utf-8")
    )
    bad = good[:-5]
    with pytest.raises(SnapshotReplayError):
        apply_tail_records(snapshot=snapshot, gzip_segments=[bad])
