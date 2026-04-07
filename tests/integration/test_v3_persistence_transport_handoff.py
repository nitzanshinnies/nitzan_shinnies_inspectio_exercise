"""P12.2: transport-backed emitter handoff integration (in-process)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from inspectio.v3.l2.app import create_l2_app
from inspectio.v3.l2.memory_enqueue import ListBulkEnqueue
from inspectio.v3.persistence_emitter.transport import TransportPersistenceEventEmitter
from inspectio.v3.persistence_transport.sqs_producer import (
    SqsPersistenceTransportProducer,
)
from inspectio.v3.schemas.send_unit import SendUnitV1
from inspectio.v3.worker.metrics import SendWorkerMetrics
from inspectio.v3.worker.scheduler import SendScheduler


class _CollectingClient:
    def __init__(self, *, always_fail: bool = False) -> None:
        self.always_fail = always_fail
        self.events: list[dict[str, object]] = []
        self.queue_urls: list[str] = []
        self.fail_count = 0

    async def send_message(self, *, QueueUrl: str, MessageBody: str) -> None:  # noqa: N803
        if self.always_fail:
            self.fail_count += 1
            raise RuntimeError("transport down")
        self.queue_urls.append(QueueUrl)
        self.events.append(json.loads(MessageBody))

    async def send_message_batch(
        self,
        *,
        QueueUrl: str,  # noqa: N803
        Entries: list[dict[str, str]],  # noqa: N803
    ) -> dict[str, list[dict[str, str]]]:
        for entry in Entries:
            await self.send_message(QueueUrl=QueueUrl, MessageBody=entry["MessageBody"])
        return {"Successful": [{"Id": e["Id"]} for e in Entries], "Failed": []}


class _OutcomesNoop:
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


def _build_transport_emitter(
    client: _CollectingClient,
) -> TransportPersistenceEventEmitter:
    producer = SqsPersistenceTransportProducer(
        queue_url="q://persist",
        client=client,
        durability_mode="best_effort",
        max_attempts=3,
        backoff_base_ms=1,
        backoff_max_ms=2,
        backoff_jitter_fraction=0.0,
        max_inflight_events=2_048,
        max_batch_events=10,
    )
    return TransportPersistenceEventEmitter(
        producer=producer,
        clock_ms=lambda: 1_700_000_000_000,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_handoff_under_load_emits_enqueued_attempt_terminal_events() -> None:
    client = _CollectingClient()
    emitter = _build_transport_emitter(client)
    backend = ListBulkEnqueue()
    app = create_l2_app(
        enqueue_backend=backend,
        clock_ms=lambda: 1_700_000_000_000,
        shard_count=1,
        persistence_emitter=emitter,
    )
    tc = TestClient(app)
    for i in range(20):
        r = tc.post("/messages/repeat?count=5", json={"body": f"b-{i}"})
        assert r.status_code == 202

    scheduler = SendScheduler(
        clock_ms=lambda: 10_000,
        try_send=lambda _m: True,
        outcomes=_OutcomesNoop(),
        delete_sqs_message=_async_none,
        metrics=SendWorkerMetrics(),
        persistence_emitter=emitter,
    )
    for i in range(20):
        unit = SendUnitV1(
            trace_id=f"trace-{i}",
            message_id=f"m-{i}",
            body="hello",
            received_at_ms=10_000,
            batch_correlation_id=f"batch-{i}",
            shard=0,
            attempts_completed=0,
        )
        await scheduler.ingest_send_unit_sqs_message(
            {"ReceiptHandle": f"rh-{i}", "Body": unit.model_dump_json(by_alias=True)},
        )
    await scheduler.wakeup_scan_due()

    kinds = [e["eventType"] for e in client.events]
    assert kinds.count("enqueued") == 20
    assert kinds.count("attempt_result") == 20
    assert kinds.count("terminal") == 20


@pytest.mark.integration
@pytest.mark.asyncio
async def test_transport_failures_do_not_crash_l2_or_worker_in_best_effort() -> None:
    client = _CollectingClient(always_fail=True)
    emitter = _build_transport_emitter(client)

    app = create_l2_app(
        enqueue_backend=ListBulkEnqueue(),
        clock_ms=lambda: 1_700_000_000_000,
        shard_count=1,
        persistence_emitter=emitter,
    )
    tc = TestClient(app)
    response = tc.post("/messages", json={"body": "x"})
    assert response.status_code == 202

    scheduler = SendScheduler(
        clock_ms=lambda: 10_000,
        try_send=lambda _m: True,
        outcomes=_OutcomesNoop(),
        delete_sqs_message=_async_none,
        metrics=SendWorkerMetrics(),
        persistence_emitter=emitter,
    )
    unit = SendUnitV1(
        trace_id="trace-f",
        message_id="m-f",
        body="hello",
        received_at_ms=10_000,
        batch_correlation_id="batch-f",
        shard=0,
        attempts_completed=0,
    )
    await scheduler.ingest_send_unit_sqs_message(
        {"ReceiptHandle": "rh-f", "Body": unit.model_dump_json(by_alias=True)},
    )
    await scheduler.wakeup_scan_due()
    assert client.fail_count > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_shard_transport_handoff_keeps_queue_segregation() -> None:
    client = _CollectingClient()
    shard_urls = ["q://persist-0", "q://persist-1"]
    from inspectio.v3.persistence_transport.sharded_router import (
        ShardedPersistenceTransportProducer,
    )

    p0 = SqsPersistenceTransportProducer(
        queue_url=shard_urls[0],
        client=client,
        durability_mode="best_effort",
        max_attempts=3,
        backoff_base_ms=1,
        backoff_max_ms=2,
        backoff_jitter_fraction=0.0,
        max_inflight_events=2_048,
        max_batch_events=10,
    )
    p1 = SqsPersistenceTransportProducer(
        queue_url=shard_urls[1],
        client=client,
        durability_mode="best_effort",
        max_attempts=3,
        backoff_base_ms=1,
        backoff_max_ms=2,
        backoff_jitter_fraction=0.0,
        max_inflight_events=2_048,
        max_batch_events=10,
    )
    emitter = TransportPersistenceEventEmitter(
        producer=ShardedPersistenceTransportProducer(producers_by_shard={0: p0, 1: p1}),
        clock_ms=lambda: 1_700_000_000_000,
    )

    scheduler = SendScheduler(
        clock_ms=lambda: 10_000,
        try_send=lambda _m: True,
        outcomes=_OutcomesNoop(),
        delete_sqs_message=_async_none,
        metrics=SendWorkerMetrics(),
        persistence_emitter=emitter,
    )
    for i in range(12):
        shard = i % 2
        unit = SendUnitV1(
            trace_id=f"trace-ms-{i}",
            message_id=f"m-ms-{i}",
            body="hello",
            received_at_ms=10_000,
            batch_correlation_id=f"batch-ms-{i}",
            shard=shard,
            attempts_completed=0,
        )
        await scheduler.ingest_send_unit_sqs_message(
            {
                "ReceiptHandle": f"rh-ms-{i}",
                "Body": unit.model_dump_json(by_alias=True),
            },
        )
    await scheduler.wakeup_scan_due()

    for payload, queue_url in zip(client.events, client.queue_urls, strict=False):
        shard = int(payload["shard"])
        assert queue_url == shard_urls[shard]


async def _async_none(_rh: str) -> None:
    return None
