"""P12.1: lifecycle persistence emitter hook tests."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from inspectio.v3.l2.app import create_l2_app
from inspectio.v3.l2.memory_enqueue import ListBulkEnqueue
from inspectio.v3.schemas.send_unit import SendUnitV1
from inspectio.v3.worker.metrics import SendWorkerMetrics
from inspectio.v3.worker.scheduler import SendScheduler


class _SpyPersistenceEmitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit_enqueued(
        self,
        *,
        trace_id: str,
        batch_correlation_id: str,
        idempotency_key: str,
        count: int,
        body: str,
        received_at_ms: int,
        shard: int,
    ) -> None:
        self.calls.append(
            {
                "kind": "enqueued",
                "trace_id": trace_id,
                "batch_correlation_id": batch_correlation_id,
                "idempotency_key": idempotency_key,
                "count": count,
                "body": body,
                "received_at_ms": received_at_ms,
                "shard": shard,
            },
        )

    async def emit_attempt_result(
        self,
        *,
        trace_id: str,
        batch_correlation_id: str,
        message_id: str,
        shard: int,
        body: str | None,
        received_at_ms: int,
        attempt_count: int,
        attempt_ok: bool,
        status: str,
        next_due_at_ms: int | None,
    ) -> None:
        self.calls.append(
            {
                "kind": "attempt_result",
                "trace_id": trace_id,
                "batch_correlation_id": batch_correlation_id,
                "message_id": message_id,
                "shard": shard,
                "body": body,
                "received_at_ms": received_at_ms,
                "attempt_count": attempt_count,
                "attempt_ok": attempt_ok,
                "status": status,
                "next_due_at_ms": next_due_at_ms,
            },
        )

    async def emit_terminal(
        self,
        *,
        trace_id: str,
        batch_correlation_id: str,
        message_id: str,
        shard: int,
        body: str | None,
        received_at_ms: int,
        attempt_count: int,
        status: str,
        final_timestamp_ms: int,
        reason: str | None,
    ) -> None:
        self.calls.append(
            {
                "kind": "terminal",
                "trace_id": trace_id,
                "batch_correlation_id": batch_correlation_id,
                "message_id": message_id,
                "shard": shard,
                "body": body,
                "received_at_ms": received_at_ms,
                "attempt_count": attempt_count,
                "status": status,
                "final_timestamp_ms": final_timestamp_ms,
                "reason": reason,
            },
        )


class _MemOutcomes:
    async def record_success(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
    ) -> None:
        return None

    async def record_failed(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
        reason: str,
    ) -> None:
        return None


def _unit(*, attempts_completed: int = 0) -> SendUnitV1:
    return SendUnitV1(
        trace_id="trace-1",
        message_id="m-1",
        body="hello",
        received_at_ms=10_000,
        batch_correlation_id="batch-1",
        shard=0,
        attempts_completed=attempts_completed,
    )


@pytest.mark.unit
def test_l2_emits_enqueued_once_for_non_duplicate_admission() -> None:
    backend = ListBulkEnqueue()
    spy = _SpyPersistenceEmitter()
    app = create_l2_app(
        enqueue_backend=backend,
        clock_ms=lambda: 1_700_000_000_000,
        shard_count=1,
        persistence_emitter=spy,
    )
    client = TestClient(app)
    response = client.post("/messages/repeat?count=3", json={"body": "x"})
    assert response.status_code == 202
    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["kind"] == "enqueued"
    assert call["count"] == 3
    assert call["body"] == "x"
    assert call["received_at_ms"] == 1_700_000_000_000


@pytest.mark.unit
def test_l2_duplicate_idempotency_does_not_emit_second_enqueued() -> None:
    backend = ListBulkEnqueue()
    spy = _SpyPersistenceEmitter()
    app = create_l2_app(
        enqueue_backend=backend,
        clock_ms=lambda: 1_700_000_000_000,
        shard_count=1,
        persistence_emitter=spy,
    )
    client = TestClient(app)
    headers = {"Idempotency-Key": "idem-1"}
    assert (
        client.post("/messages", json={"body": "x"}, headers=headers).status_code == 202
    )
    assert (
        client.post("/messages", json={"body": "x"}, headers=headers).status_code == 202
    )
    assert len(spy.calls) == 1
    assert spy.calls[0]["kind"] == "enqueued"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scheduler_success_emits_attempt_then_terminal() -> None:
    t = [10_000]

    def clock() -> int:
        return t[0]

    spy = _SpyPersistenceEmitter()
    scheduler = SendScheduler(
        clock_ms=clock,
        try_send=lambda _m: True,
        outcomes=_MemOutcomes(),
        delete_sqs_message=lambda _rh: _async_none(),
        metrics=SendWorkerMetrics(),
        persistence_emitter=spy,
    )
    unit = _unit()
    await scheduler.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-1", "Body": unit.model_dump_json(by_alias=True)},
    )
    await scheduler.wakeup_scan_due()
    kinds = [c["kind"] for c in spy.calls]
    assert kinds == ["attempt_result", "terminal"]
    assert spy.calls[0]["attempt_ok"] is True
    assert spy.calls[0]["attempt_count"] == 1
    assert spy.calls[1]["status"] == "success"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scheduler_non_terminal_failure_emits_attempt_only_with_next_due() -> (
    None
):
    t = [10_000]

    def clock() -> int:
        return t[0]

    spy = _SpyPersistenceEmitter()
    scheduler = SendScheduler(
        clock_ms=clock,
        try_send=lambda _m: False,
        outcomes=_MemOutcomes(),
        delete_sqs_message=lambda _rh: _async_none(),
        metrics=SendWorkerMetrics(),
        persistence_emitter=spy,
    )
    unit = _unit()
    await scheduler.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-2", "Body": unit.model_dump_json(by_alias=True)},
    )
    await scheduler.wakeup_scan_due()
    assert [c["kind"] for c in spy.calls] == ["attempt_result"]
    assert spy.calls[0]["status"] == "pending"
    assert spy.calls[0]["next_due_at_ms"] == 10_500


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scheduler_terminal_failure_emits_attempt_then_terminal() -> None:
    t = [30_000]

    def clock() -> int:
        return t[0]

    spy = _SpyPersistenceEmitter()
    scheduler = SendScheduler(
        clock_ms=clock,
        try_send=lambda _m: False,
        outcomes=_MemOutcomes(),
        delete_sqs_message=lambda _rh: _async_none(),
        metrics=SendWorkerMetrics(),
        persistence_emitter=spy,
    )
    unit = _unit(attempts_completed=5)
    await scheduler.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-3", "Body": unit.model_dump_json(by_alias=True)},
    )
    await scheduler.wakeup_scan_due()
    kinds = [c["kind"] for c in spy.calls]
    assert kinds == ["attempt_result", "terminal"]
    assert spy.calls[0]["attempt_ok"] is False
    assert spy.calls[0]["status"] == "failed"
    assert spy.calls[1]["status"] == "failed"
    assert spy.calls[1]["reason"] == "max_try_send_failures"


async def _async_none() -> None:
    return None
