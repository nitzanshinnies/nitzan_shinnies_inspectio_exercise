"""Unit tests for writer queue-age observability semantics."""

from __future__ import annotations

import asyncio

import pytest

from inspectio.v3.persistence_writer.metrics import PersistenceWriterMetrics
from inspectio.v3.persistence_writer.main import (
    QueueOldestAgeSample,
    _drain_ack_batch,
    _drain_ack_queue_nowait,
    _enqueue_ack_events,
    _flush_loop_iteration,
    _maybe_refresh_queue_oldest_age,
    _shutdown_flush_and_ack,
)
from inspectio.v3.schemas.persistence_event import PersistenceEventV1


class _QueueAgeConsumer:
    def __init__(self, *, age_ms: int | None, should_fail: bool = False) -> None:
        self.age_ms = age_ms
        self.should_fail = should_fail
        self.calls = 0

    async def queue_oldest_age_ms(self) -> int | None:
        self.calls += 1
        if self.should_fail:
            raise RuntimeError("queue age fetch failed")
        return self.age_ms


class _FakeFlushWriter:
    def __init__(
        self,
        *,
        flushed: list[PersistenceEventV1],
        should_fail: bool = False,
        expect_force: bool = False,
    ) -> None:
        self._flushed = flushed
        self._should_fail = should_fail
        self._expect_force = expect_force
        self.metrics = PersistenceWriterMetrics()

    async def flush_due(self, *, force: bool) -> list[PersistenceEventV1]:
        assert force is self._expect_force
        if self._should_fail:
            raise RuntimeError("flush failed")
        return self._flushed


def _event(event_id: str) -> PersistenceEventV1:
    return PersistenceEventV1.model_validate(
        {
            "schemaVersion": 1,
            "eventId": event_id,
            "eventType": "attempt_result",
            "emittedAtMs": 1_000,
            "shard": 0,
            "segmentSeq": 1,
            "segmentEventIndex": 0,
            "traceId": "t",
            "batchCorrelationId": "b",
            "messageId": f"m-{event_id}",
            "attemptCount": 1,
            "attemptOk": True,
            "status": "pending",
            "nextDueAtMs": 2_000,
            "receivedAtMs": 1_100,
            "body": "payload",
        }
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_queue_age_sampler_uses_queue_metric_and_respects_interval() -> None:
    consumer = _QueueAgeConsumer(age_ms=42_000)
    sample = QueueOldestAgeSample()
    updated = await _maybe_refresh_queue_oldest_age(
        consumer=consumer,
        sample=sample,
        now_ms=1_000,
        sample_interval_ms=30_000,
        timeout_sec=1.0,
    )
    assert consumer.calls == 1
    assert updated.age_ms == 42_000
    assert updated.sampled_at_ms == 1_000

    unchanged = await _maybe_refresh_queue_oldest_age(
        consumer=consumer,
        sample=updated,
        now_ms=2_000,
        sample_interval_ms=30_000,
        timeout_sec=1.0,
    )
    assert consumer.calls == 1
    assert unchanged.sampled_at_ms == 1_000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_queue_age_sampler_retains_last_known_value_on_failure() -> None:
    consumer = _QueueAgeConsumer(age_ms=10_000)
    sample = QueueOldestAgeSample()
    sample = await _maybe_refresh_queue_oldest_age(
        consumer=consumer,
        sample=sample,
        now_ms=1_000,
        sample_interval_ms=1,
        timeout_sec=1.0,
    )
    assert sample.age_ms == 10_000
    assert sample.sampled_at_ms == 1_000

    failing_consumer = _QueueAgeConsumer(age_ms=None, should_fail=True)
    after_failure = await _maybe_refresh_queue_oldest_age(
        consumer=failing_consumer,
        sample=sample,
        now_ms=2_500,
        sample_interval_ms=1,
        timeout_sec=1.0,
    )
    assert failing_consumer.calls == 1
    assert after_failure.age_ms == 10_000
    assert after_failure.sampled_at_ms == 1_000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_ack_events_records_blocked_push_when_queue_full() -> None:
    metrics = PersistenceWriterMetrics()
    queue: asyncio.Queue[PersistenceEventV1] = asyncio.Queue(maxsize=1)
    queue.put_nowait(_event("preloaded"))
    metrics.observe_ack_queue_depth(depth=queue.qsize())

    async def _delayed_consume() -> None:
        await asyncio.sleep(0.02)
        _ = await queue.get()
        queue.task_done()

    consumer_task = asyncio.create_task(_delayed_consume())
    await _enqueue_ack_events(
        ack_queue=queue,
        events=[_event("to-enqueue")],
        metrics=metrics,
    )
    await consumer_task
    assert metrics.ack_queue_blocked_push_total >= 1
    assert metrics.ack_queue_depth_high_water_mark >= 1


@pytest.mark.unit
def test_drain_ack_batch_coalesces_queue_items() -> None:
    queue: asyncio.Queue[PersistenceEventV1] = asyncio.Queue(maxsize=10)
    first = _event("a1")
    queue.put_nowait(_event("a2"))
    queue.put_nowait(_event("a3"))
    drained = _drain_ack_batch(ack_queue=queue, first=first, max_events=3)
    assert [item.event_id for item in drained] == ["a1", "a2", "a3"]
    assert queue.qsize() == 0


@pytest.mark.unit
def test_drain_ack_queue_nowait_returns_empty_when_queue_empty() -> None:
    queue: asyncio.Queue[PersistenceEventV1] = asyncio.Queue(maxsize=1)
    drained = _drain_ack_queue_nowait(ack_queue=queue)
    assert drained == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flush_iteration_enqueues_only_after_flush_success() -> None:
    writer = _FakeFlushWriter(flushed=[_event("ok")])
    lock = asyncio.Lock()
    captured: list[list[PersistenceEventV1]] = []

    async def _enqueue(events: list[PersistenceEventV1]) -> None:
        captured.append(events)

    had_flush = await _flush_loop_iteration(
        writer=writer,
        writer_lock=lock,
        enqueue_for_ack=_enqueue,
    )
    assert had_flush is True
    assert len(captured) == 1
    assert captured[0][0].event_id == "ok"

    failing_writer = _FakeFlushWriter(flushed=[_event("ignored")], should_fail=True)
    captured_after_fail: list[list[PersistenceEventV1]] = []

    async def _enqueue_fail(events: list[PersistenceEventV1]) -> None:
        captured_after_fail.append(events)

    with pytest.raises(RuntimeError):
        await _flush_loop_iteration(
            writer=failing_writer,
            writer_lock=lock,
            enqueue_for_ack=_enqueue_fail,
        )
    assert captured_after_fail == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shutdown_flush_and_ack_does_not_depend_on_queue_consumer() -> None:
    writer = _FakeFlushWriter(flushed=[_event("final-1")], expect_force=True)
    lock = asyncio.Lock()
    ack_queue: asyncio.Queue[PersistenceEventV1] = asyncio.Queue(maxsize=2)
    ack_queue.put_nowait(_event("queued-1"))
    ack_queue.put_nowait(_event("queued-2"))
    writer.metrics.observe_ack_queue_depth(depth=ack_queue.qsize())
    acked_event_ids: list[str] = []

    async def _ack_many(events: list[PersistenceEventV1]) -> int:
        acked_event_ids.extend(event.event_id for event in events)
        return 7

    await _shutdown_flush_and_ack(
        writer=writer,
        writer_lock=lock,
        ack_queue=ack_queue,
        ack_many_with_retry=_ack_many,
        clock_ms=lambda: 12345,
    )

    assert ack_queue.qsize() == 0
    assert set(acked_event_ids) == {"final-1", "queued-1", "queued-2"}
    assert writer.metrics.ack_queue_depth_current == 0
