"""P4: SendScheduler deadlines, terminal outcomes, dedupe (unit)."""

from __future__ import annotations

import pytest

from inspectio.v3.assignment_surface import Message
from inspectio.v3.schemas.send_unit import SendUnitV1
from inspectio.v3.worker.metrics import SendWorkerMetrics
from inspectio.v3.worker.scheduler import SendScheduler


def _unit(mid: str = "m-1") -> SendUnitV1:
    return SendUnitV1(
        trace_id="t1",
        message_id=mid,
        body="hello",
        received_at_ms=10_000,
        batch_correlation_id="b1",
        shard=0,
        attempts_completed=0,
    )


class _MemOutcomes:
    def __init__(self) -> None:
        self.success: list[dict[str, object]] = []
        self.failed: list[dict[str, object]] = []

    async def record_success(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
    ) -> None:
        self.success.append(
            {
                "message_id": message_id,
                "attempt_count": attempt_count,
                "final_timestamp_ms": final_timestamp_ms,
            },
        )

    async def record_failed(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
        reason: str,
    ) -> None:
        self.failed.append(
            {
                "message_id": message_id,
                "attempt_count": attempt_count,
                "final_timestamp_ms": final_timestamp_ms,
                "reason": reason,
            },
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_success_first_try_deletes_sqs() -> None:
    t = [10_000]

    def clock() -> int:
        return t[0]

    outcomes = _MemOutcomes()
    deleted: list[str] = []

    async def delete_rh(rh: str) -> None:
        deleted.append(rh)

    sched = SendScheduler(
        clock_ms=clock,
        try_send=lambda _m: True,
        outcomes=outcomes,
        delete_sqs_message=delete_rh,
        metrics=SendWorkerMetrics(),
    )
    u = _unit()
    await sched.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-a", "Body": u.model_dump_json(by_alias=True)},
    )
    await sched.wakeup_scan_due()
    assert len(outcomes.success) == 1
    assert outcomes.success[0]["attempt_count"] == 1
    assert deleted == ["rh-a"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_six_failures_catch_up_one_wakeup() -> None:
    t = [26_000]

    def clock() -> int:
        return t[0]

    outcomes = _MemOutcomes()
    deleted: list[str] = []

    async def delete_rh(rh: str) -> None:
        deleted.append(rh)

    metrics = SendWorkerMetrics()
    sched = SendScheduler(
        clock_ms=clock,
        try_send=lambda _m: False,
        outcomes=outcomes,
        delete_sqs_message=delete_rh,
        metrics=metrics,
    )
    u = _unit()
    await sched.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-f", "Body": u.model_dump_json(by_alias=True)},
    )
    await sched.wakeup_scan_due()
    assert len(outcomes.failed) == 1
    assert outcomes.failed[0]["attempt_count"] == 6
    assert outcomes.failed[0]["reason"] == "max_try_send_failures"
    assert deleted == ["rh-f"]
    assert metrics.send_fail == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicate_delivery_deletes_extra_receipt() -> None:
    t = [10_000]

    def clock() -> int:
        return t[0]

    outcomes = _MemOutcomes()
    deleted: list[str] = []

    async def delete_rh(rh: str) -> None:
        deleted.append(rh)

    sched = SendScheduler(
        clock_ms=clock,
        try_send=lambda _m: True,
        outcomes=outcomes,
        delete_sqs_message=delete_rh,
        metrics=SendWorkerMetrics(),
    )
    u = _unit()
    await sched.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-1", "Body": u.model_dump_json(by_alias=True)},
    )
    await sched.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-2", "Body": u.model_dump_json(by_alias=True)},
    )
    assert deleted == ["rh-2"]
    await sched.wakeup_scan_due()
    assert len(outcomes.success) == 1
    assert deleted == ["rh-2", "rh-1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_try_send_async_supported() -> None:
    t = [10_000]

    def clock() -> int:
        return t[0]

    outcomes = _MemOutcomes()
    deleted: list[str] = []

    async def delete_rh(rh: str) -> None:
        deleted.append(rh)

    async def try_async(_m: Message) -> bool:
        return True

    sched = SendScheduler(
        clock_ms=clock,
        try_send=try_async,
        outcomes=outcomes,
        delete_sqs_message=delete_rh,
        metrics=SendWorkerMetrics(),
    )
    u = _unit()
    await sched.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-z", "Body": u.model_dump_json(by_alias=True)},
    )
    await sched.wakeup_scan_due()
    assert outcomes.success and deleted == ["rh-z"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_stub_called_on_success_with_terminal_payload() -> None:
    t = [10_000]

    def clock() -> int:
        return t[0]

    outcomes = _MemOutcomes()
    deleted: list[str] = []
    persist: list[dict[str, object]] = []

    async def delete_rh(rh: str) -> None:
        deleted.append(rh)

    async def persist_stub(payload: dict[str, object]) -> None:
        persist.append(payload)

    sched = SendScheduler(
        clock_ms=clock,
        try_send=lambda _m: True,
        outcomes=outcomes,
        delete_sqs_message=delete_rh,
        metrics=SendWorkerMetrics(),
        persist_terminal_stub=persist_stub,
    )
    u = _unit()
    await sched.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-p", "Body": u.model_dump_json(by_alias=True)},
    )
    await sched.wakeup_scan_due()
    assert len(persist) == 1
    assert persist[0]["terminalStatus"] == "success"
    assert persist[0]["messageId"] == "m-1"
    assert persist[0]["traceId"] == "t1"
    assert persist[0]["batchCorrelationId"] == "b1"
    assert persist[0]["shard"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_persist_stub_called_on_failed_terminal() -> None:
    t = [26_000]

    def clock() -> int:
        return t[0]

    outcomes = _MemOutcomes()
    persist: list[dict[str, object]] = []

    async def persist_stub(payload: dict[str, object]) -> None:
        persist.append(payload)

    async def delete_rh(_rh: str) -> None:
        return None

    sched = SendScheduler(
        clock_ms=clock,
        try_send=lambda _m: False,
        outcomes=outcomes,
        delete_sqs_message=delete_rh,
        metrics=SendWorkerMetrics(),
        persist_terminal_stub=persist_stub,
    )
    u = _unit()
    await sched.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-pf", "Body": u.model_dump_json(by_alias=True)},
    )
    await sched.wakeup_scan_due()
    assert len(persist) == 1
    assert persist[0]["terminalStatus"] == "failed"
    assert persist[0]["reason"] == "max_try_send_failures"
    assert persist[0]["attemptCount"] == 6
