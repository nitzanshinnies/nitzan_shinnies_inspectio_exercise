"""P8 multi-shard orchestration tests for worker/main helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from inspectio.journal.records import JournalRecordV1
from inspectio.worker.main import (
    ShardedJournalFacade,
    _owned_shard_ids,
    _publish_terminal_outcomes,
    _restore_runtime_from_s3_snapshots,
    _terminal_payload_from_record,
)
from inspectio.worker.runtime import InMemorySchedulerRuntime


@dataclass
class _FakeWriter:
    shard_id: int
    appended: int = 0
    flushed: int = 0
    snapshots: list[int] | None = None
    last_snapshot_ms: int | None = None

    async def append(self, record: JournalRecordV1) -> None:
        assert record.shard_id == self.shard_id
        self.appended += 1

    async def flush(self, *, force: bool = False) -> None:
        _ = force
        self.flushed += 1

    async def write_snapshot_if_due(
        self,
        *,
        shard_id: int,
        last_record_index: int,
        active: dict[str, dict[str, Any]],
        now_ms: int,
    ) -> None:
        _ = last_record_index
        _ = active
        assert shard_id == self.shard_id
        if self.snapshots is None:
            self.snapshots = []
        if self.last_snapshot_ms is None or now_ms - self.last_snapshot_ms >= 60_000:
            self.snapshots.append(now_ms)
            self.last_snapshot_ms = now_ms


def _record(shard_id: int, record_index: int) -> JournalRecordV1:
    return JournalRecordV1.model_validate(
        {
            "v": 1,
            "type": "INGEST_APPLIED",
            "shardId": shard_id,
            "messageId": f"m-{shard_id}-{record_index}",
            "tsMs": 1_700_000_000_000 + record_index,
            "recordIndex": record_index,
            "payload": {
                "receivedAtMs": 1_700_000_000_000,
                "idempotencyKey": f"k-{shard_id}-{record_index}",
                "bodyHash": "a" * 64,
            },
        }
    )


@pytest.mark.unit
def test_owned_shard_ids_uses_section_16_range_math() -> None:
    # total_shards=10, replicas=3, worker 1 owns [4, 8)
    assert _owned_shard_ids(worker_index=1, total_shards=10, worker_replicas=3) == [
        4,
        5,
        6,
        7,
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sharded_writer_routes_records_per_shard_without_cross_shard_error() -> (
    None
):
    writers: dict[int, _FakeWriter] = {}

    def _factory(shard_id: int) -> _FakeWriter:
        w = _FakeWriter(shard_id=shard_id)
        writers[shard_id] = w
        return w

    facade = ShardedJournalFacade(writer_factory=_factory, managed_shards={7, 8})
    await facade.append(_record(7, 1))
    await facade.append(_record(8, 1))
    await facade.flush()
    assert writers[7].appended == 1
    assert writers[8].appended == 1
    assert writers[7].flushed == 1
    assert writers[8].flushed == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_snapshot_cadence_is_independent_per_shard() -> None:
    writers: dict[int, _FakeWriter] = {}

    def _factory(shard_id: int) -> _FakeWriter:
        w = _FakeWriter(shard_id=shard_id)
        writers[shard_id] = w
        return w

    facade = ShardedJournalFacade(writer_factory=_factory, managed_shards={7, 8})
    await facade.write_snapshot_if_due(
        shard_id=7,
        last_record_index=1,
        active={},
        now_ms=1_000,
    )
    await facade.write_snapshot_if_due(
        shard_id=8,
        last_record_index=1,
        active={},
        now_ms=1_000,
    )
    # shard 7 not due at 59s; shard 8 due at 61s
    await facade.write_snapshot_if_due(
        shard_id=7,
        last_record_index=2,
        active={},
        now_ms=59_000,
    )
    await facade.write_snapshot_if_due(
        shard_id=8,
        last_record_index=2,
        active={},
        now_ms=61_000,
    )
    assert writers[7].snapshots == [1_000]
    assert writers[8].snapshots == [1_000, 61_000]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_restore_calls_replay_for_all_owned_shards() -> None:
    class _FakeReplayStore:
        def __init__(self) -> None:
            self.load_calls: list[int] = []

        async def load_latest(self, *, shard_id: int):
            self.load_calls.append(shard_id)
            return None

        async def load_tail_segments(self, *, shard_id: int):
            _ = shard_id
            return []

    class _NeverSend:
        async def send(self, _message, _attempt_index):
            return False

    runtime = InMemorySchedulerRuntime(now_ms=lambda: 1000, sms_sender=_NeverSend())
    replay = _FakeReplayStore()
    await _restore_runtime_from_s3_snapshots(
        runtime=runtime, replay_store=replay, shard_ids=[4, 5, 6, 7]
    )
    assert replay.load_calls == [4, 5, 6, 7]


@pytest.mark.unit
def test_terminal_payload_maps_runtime_terminal_record_shape() -> None:
    terminal = JournalRecordV1.model_validate(
        {
            "v": 1,
            "type": "TERMINAL",
            "shardId": 3,
            "messageId": "m-1",
            "tsMs": 1_700_000_000_321,
            "recordIndex": 9,
            "payload": {"status": "failed", "attemptCount": 6, "reason": "send_failed"},
        }
    )
    payload = _terminal_payload_from_record(terminal)
    assert payload == {
        "messageId": "m-1",
        "terminalStatus": "failed",
        "attemptCount": 6,
        "finalTimestampMs": 1_700_000_000_321,
        "reason": "send_failed",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publish_terminal_outcomes_posts_only_terminal_lines() -> None:
    class _FakeNotificationClient:
        def __init__(self) -> None:
            self.posted: list[dict[str, object]] = []

        async def post_terminal(self, payload: dict[str, object]) -> None:
            self.posted.append(payload)

    lines = [
        _record(7, 1),
        JournalRecordV1.model_validate(
            {
                "v": 1,
                "type": "TERMINAL",
                "shardId": 7,
                "messageId": "m-7",
                "tsMs": 1000,
                "recordIndex": 2,
                "payload": {"status": "success", "attemptCount": 1},
            }
        ),
    ]
    client = _FakeNotificationClient()
    await _publish_terminal_outcomes(lines=lines, notification_client=client)
    assert client.posted == [
        {
            "messageId": "m-7",
            "terminalStatus": "success",
            "attemptCount": 1,
            "finalTimestampMs": 1000,
            "reason": None,
        }
    ]
