"""P6 scheduler/runtime tests (TC-SUR-*, TC-CON-*, TC-FLT-003)."""

from __future__ import annotations

import asyncio

import pytest

from inspectio.journal.records import JournalRecordV1
from inspectio.models import Message
from inspectio.worker.runtime import InMemorySchedulerRuntime


class _RecordingSmsSender:
    def __init__(self, outcomes: list[bool] | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self._outcomes = outcomes or [True]

    async def send(self, message: Message, attempt_index: int) -> bool:
        self.calls.append((message.message_id, attempt_index))
        idx = len(self.calls) - 1
        if idx >= len(self._outcomes):
            return self._outcomes[-1]
        return self._outcomes[idx]


class _TimeoutOnFirstSmsSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self._first = True

    async def send(self, message: Message, attempt_index: int) -> bool:
        self.calls.append((message.message_id, attempt_index))
        if self._first:
            self._first = False
            raise TimeoutError("connect_timeout")
        return False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_sur_001_new_message_attempts_immediately_once() -> None:
    sms = _RecordingSmsSender([True])
    rt = InMemorySchedulerRuntime(now_ms=lambda: 1000, sms_sender=sms)
    msg = Message(message_id="m-1", to="+1", body="hello")
    await rt.new_message(msg)

    assert sms.calls == [("m-1", 0)]
    assert _types(rt.journal) == ["SEND_ATTEMPTED", "SEND_RESULT", "TERMINAL"]
    assert rt.journal[-1].payload["attemptCount"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_sur_002_succeeds_on_sixth_send() -> None:
    sms = _RecordingSmsSender([False, False, False, False, False, True])
    now_ms = 1_700_000_000_000
    clock = {"now": now_ms}
    rt = InMemorySchedulerRuntime(now_ms=lambda: clock["now"], sms_sender=sms)
    msg = Message(message_id="m-2", to="+1", body="hello")
    await rt.new_message(msg)
    for _ in range(8):
        clock["now"] += 60_000
        await rt.wakeup()

    assert len(sms.calls) == 6
    assert rt.journal[-1].type == "TERMINAL"
    assert rt.journal[-1].payload["status"] == "success"
    assert rt.journal[-1].payload["attemptCount"] == 6


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_sur_003_always_fail_reaches_terminal_failed_attempt_6() -> None:
    sms = _RecordingSmsSender([False, False, False, False, False, False])
    now_ms = 1_700_000_000_000
    clock = {"now": now_ms}
    rt = InMemorySchedulerRuntime(now_ms=lambda: clock["now"], sms_sender=sms)
    msg = Message(message_id="m-3", to="+1", body="hello")
    await rt.new_message(msg)
    for _ in range(8):
        clock["now"] += 60_000
        await rt.wakeup()

    assert len(sms.calls) == 6
    assert rt.journal[-1].type == "TERMINAL"
    assert rt.journal[-1].payload["status"] == "failed"
    assert rt.journal[-1].payload["attemptCount"] == 6


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_sur_004_wakeup_with_empty_due_set_makes_zero_send_calls() -> None:
    sms = _RecordingSmsSender([True])
    rt = InMemorySchedulerRuntime(now_ms=lambda: 0, sms_sender=sms)
    await rt.wakeup()
    assert sms.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_dom_007_wakeup_before_due_does_not_send() -> None:
    sms = _RecordingSmsSender([False, True])
    clock = {"now": 1_700_000_000_000}
    rt = InMemorySchedulerRuntime(now_ms=lambda: clock["now"], sms_sender=sms)
    await rt.new_message(Message(message_id="m-dom-7", to="+1", body="hello"))
    # After first failure, next due is arrival + 500.
    clock["now"] = 1_700_000_000_499
    await rt.wakeup()
    assert len(sms.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_dom_008_wakeup_at_due_may_send() -> None:
    sms = _RecordingSmsSender([False, True])
    clock = {"now": 1_700_000_000_000}
    rt = InMemorySchedulerRuntime(now_ms=lambda: clock["now"], sms_sender=sms)
    await rt.new_message(Message(message_id="m-dom-8", to="+1", body="hello"))
    clock["now"] = 1_700_000_000_500
    await rt.wakeup()
    assert len(sms.calls) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_flt_003_timeout_treated_as_failure_and_schedules_next_due() -> None:
    sender = _TimeoutOnFirstSmsSender()
    clock = {"now": 1_700_000_000_000}
    rt = InMemorySchedulerRuntime(now_ms=lambda: clock["now"], sms_sender=sender)
    msg = Message(message_id="m-4", to="+1", body="hello")
    await rt.new_message(msg)
    next_due_records = [r for r in rt.journal if r.type == "NEXT_DUE"]
    assert len(next_due_records) == 1
    assert next_due_records[0].payload["attemptCount"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_con_001_same_message_never_has_overlapping_send() -> None:
    in_flight = 0
    overlap = {"seen": False}

    class _GuardSender:
        async def send(self, message: Message, attempt_index: int) -> bool:
            nonlocal in_flight
            _ = message
            _ = attempt_index
            in_flight += 1
            if in_flight > 1:
                overlap["seen"] = True
            await asyncio.sleep(0)
            in_flight -= 1
            return False

    clock = {"now": 1_700_000_000_000}
    rt = InMemorySchedulerRuntime(
        now_ms=lambda: clock["now"], sms_sender=_GuardSender()
    )
    msg = Message(message_id="m-5", to="+1", body="hello")
    await rt.new_message(msg)
    tasks = []
    for _ in range(20):
        clock["now"] += 60_000
        tasks.append(asyncio.create_task(rt.wakeup()))
    await asyncio.gather(*tasks)
    assert not overlap["seen"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tc_con_002_two_message_ids_may_send_in_parallel() -> None:
    in_flight = 0
    peak = {"value": 0}

    class _ParallelSender:
        async def send(self, message: Message, attempt_index: int) -> bool:
            nonlocal in_flight
            _ = message
            _ = attempt_index
            in_flight += 1
            peak["value"] = max(peak["value"], in_flight)
            await asyncio.sleep(0)
            in_flight -= 1
            return True

    rt = InMemorySchedulerRuntime(
        now_ms=lambda: 1_700_000_000_000, sms_sender=_ParallelSender()
    )
    await asyncio.gather(
        rt.new_message(Message(message_id="m-6", to="+1", body="a")),
        rt.new_message(Message(message_id="m-7", to="+1", body="b")),
    )
    assert peak["value"] >= 2


def _types(records: list[JournalRecordV1]) -> list[str]:
    return [r.type for r in records]
