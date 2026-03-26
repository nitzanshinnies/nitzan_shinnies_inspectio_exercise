"""P6 worker main cadence tests."""

from __future__ import annotations

import asyncio

import pytest

from inspectio.journal.replay import ReplayState
from inspectio.worker.main import _restore_runtime_from_s3_snapshots, run_consumer_loop
from inspectio.worker.runtime import InMemorySchedulerRuntime


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_consumer_loop_sleeps_for_remaining_cadence() -> None:
    consume_calls = 0
    wakeup_calls = 0
    sleeps: list[float] = []

    async def _consume_once() -> int:
        nonlocal consume_calls
        consume_calls += 1
        if consume_calls >= 2:
            raise asyncio.CancelledError
        return 0

    async def _wakeup_once() -> int:
        nonlocal wakeup_calls
        wakeup_calls += 1
        return 0

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with pytest.raises(asyncio.CancelledError):
        await run_consumer_loop(
            consume_once=_consume_once,
            wakeup_once=_wakeup_once,
            poll_interval_sec=0.5,
            sleep_func=_sleep,
        )

    assert consume_calls >= 2
    assert wakeup_calls >= 1
    assert sleeps
    assert all(s >= 0 for s in sleeps)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_restore_runtime_from_snapshot_and_tail_replay() -> None:
    class _FakeReplayStore:
        async def load_latest(self, *, shard_id: int) -> ReplayState | None:
            _ = shard_id
            return ReplayState(
                shard_id=0,
                last_record_index=1,
                active={
                    "m-1": {
                        "messageId": "m-1",
                        "attemptCount": 1,
                        "nextDueAtMs": 1000,
                        "status": "pending",
                        "lastError": None,
                        "payload": {"to": "+1", "body": "x"},
                    }
                },
            )

        async def load_tail_segments(self, *, shard_id: int) -> list[bytes]:
            _ = shard_id
            return []

    class _NeverSend:
        async def send(self, _message, _attempt_index):
            return False

    runtime = InMemorySchedulerRuntime(now_ms=lambda: 1000, sms_sender=_NeverSend())
    await _restore_runtime_from_s3_snapshots(
        runtime=runtime,
        replay_store=_FakeReplayStore(),
        shard_ids=[0],
    )
    assert runtime.active_snapshot_view_by_shard()[0]["m-1"]["attemptCount"] == 1
