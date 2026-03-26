"""P8 snapshot emission tests for journal writer."""

from __future__ import annotations

import json
from typing import Any

import pytest

from inspectio.journal.writer import JournalWriter


class _CaptureS3:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"ETag": "x"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_writer_emits_latest_and_epoch_snapshot_keys() -> None:
    s3 = _CaptureS3()
    writer = JournalWriter(
        s3_client=s3,
        bucket="bucket-a",
        flush_interval_ms=50,
        flush_max_lines=64,
        snapshot_interval_sec=60,
    )
    active = {
        "m-1": {
            "messageId": "m-1",
            "attemptCount": 2,
            "nextDueAtMs": 1_700_000_000_900,
            "status": "pending",
            "lastError": None,
            "payload": {"to": "+1", "body": "hello"},
        }
    }
    await writer.write_snapshot(
        shard_id=7,
        last_record_index=123,
        active=active,
        captured_at_ms=1_700_000_000_000,
    )

    keys = [str(c["Key"]) for c in s3.calls]
    assert "state/snapshot/7/latest.json" in keys
    assert "state/snapshot/7/1700000000000.json" in keys
    latest = next(c for c in s3.calls if c["Key"] == "state/snapshot/7/latest.json")
    payload = json.loads(bytes(latest["Body"]).decode("utf-8"))
    assert payload["lastRecordIndex"] == 123
    assert payload["active"]["m-1"]["status"] == "pending"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_writer_snapshot_interval_guard() -> None:
    s3 = _CaptureS3()
    writer = JournalWriter(
        s3_client=s3,
        bucket="bucket-a",
        flush_interval_ms=50,
        flush_max_lines=64,
        snapshot_interval_sec=60,
    )
    active: dict[str, dict[str, Any]] = {}

    await writer.write_snapshot_if_due(
        shard_id=7, last_record_index=1, active=active, now_ms=1000
    )
    assert len(s3.calls) == 2

    await writer.write_snapshot_if_due(
        shard_id=7, last_record_index=2, active=active, now_ms=59_000
    )
    assert len(s3.calls) == 2

    await writer.write_snapshot_if_due(
        shard_id=7, last_record_index=3, active=active, now_ms=61_000
    )
    assert len(s3.calls) == 4
