"""P12.2: SQS persistence producer retry, DLQ, backpressure."""

from __future__ import annotations

import asyncio
import json

import pytest

from inspectio.v3.persistence_transport.errors import (
    PersistenceTransportBackpressureError,
    PersistenceTransportPublishError,
)
from inspectio.v3.persistence_transport.sqs_producer import (
    SqsPersistenceTransportProducer,
)
from inspectio.v3.schemas.persistence_event import PersistenceEventV1


def _event(event_id: str) -> PersistenceEventV1:
    return PersistenceEventV1.model_validate(
        {
            "schemaVersion": 1,
            "eventId": event_id,
            "eventType": "terminal",
            "emittedAtMs": 100,
            "shard": 0,
            "segmentSeq": 1,
            "segmentEventIndex": 0,
            "traceId": "t",
            "batchCorrelationId": "b",
            "messageId": "m",
            "receivedAtMs": 99,
            "attemptCount": 1,
            "status": "success",
            "finalTimestampMs": 111,
        },
    )


class _Client:
    def __init__(
        self,
        *,
        fail_times: int = 0,
        fail_primary_only: bool = False,
        sleep_on_send_sec: float = 0.0,
    ) -> None:
        self.fail_times = fail_times
        self.fail_primary_only = fail_primary_only
        self.sleep_on_send_sec = sleep_on_send_sec
        self.primary: list[str] = []
        self.dlq: list[str] = []

    async def send_message(self, *, QueueUrl: str, MessageBody: str) -> None:  # noqa: N803
        if self.sleep_on_send_sec > 0:
            await asyncio.sleep(self.sleep_on_send_sec)
        is_dlq = "dlq" in QueueUrl
        should_fail = self.fail_times > 0 and (not self.fail_primary_only or not is_dlq)
        if should_fail:
            self.fail_times -= 1
            raise RuntimeError("boom")
        if is_dlq:
            self.dlq.append(MessageBody)
        else:
            self.primary.append(MessageBody)

    async def send_message_batch(
        self,
        *,
        QueueUrl: str,  # noqa: N803
        Entries: list[dict[str, str]],  # noqa: N803
    ) -> dict[str, list[dict[str, str]]]:
        for entry in Entries:
            await self.send_message(QueueUrl=QueueUrl, MessageBody=entry["MessageBody"])
        return {"Successful": [{"Id": e["Id"]} for e in Entries], "Failed": []}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publish_retries_then_succeeds() -> None:
    client = _Client(fail_times=2)
    producer = SqsPersistenceTransportProducer(
        queue_url="q://primary",
        client=client,
        durability_mode="best_effort",
        max_attempts=4,
        backoff_base_ms=1,
        backoff_max_ms=2,
        backoff_jitter_fraction=0.0,
        max_inflight_events=32,
        max_batch_events=10,
    )
    await producer.publish(_event("e-1"))
    assert len(client.primary) == 1
    assert producer.metrics.publish_retries >= 2
    payload = json.loads(client.primary[0])
    assert payload["eventId"] == "e-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_best_effort_failure_sends_to_dlq_no_crash() -> None:
    client = _Client(fail_times=99, fail_primary_only=True)
    producer = SqsPersistenceTransportProducer(
        queue_url="q://primary",
        dlq_queue_url="q://dlq",
        client=client,
        durability_mode="best_effort",
        max_attempts=2,
        backoff_base_ms=1,
        backoff_max_ms=1,
        backoff_jitter_fraction=0.0,
        max_inflight_events=32,
        max_batch_events=10,
    )
    await producer.publish(_event("e-2"))
    assert producer.metrics.publish_failures == 1
    assert producer.metrics.dlq_published_ok == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_strict_mode_raises_on_exhausted_retries() -> None:
    client = _Client(fail_times=99)
    producer = SqsPersistenceTransportProducer(
        queue_url="q://primary",
        client=client,
        durability_mode="strict",
        max_attempts=2,
        backoff_base_ms=1,
        backoff_max_ms=1,
        backoff_jitter_fraction=0.0,
        max_inflight_events=32,
        max_batch_events=10,
    )
    with pytest.raises(PersistenceTransportPublishError):
        await producer.publish(_event("e-3"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_backpressure_best_effort_drops_when_inflight_cap_exceeded() -> None:
    client = _Client(sleep_on_send_sec=0.1)
    producer = SqsPersistenceTransportProducer(
        queue_url="q://primary",
        client=client,
        durability_mode="best_effort",
        max_attempts=2,
        backoff_base_ms=1,
        backoff_max_ms=1,
        backoff_jitter_fraction=0.0,
        max_inflight_events=1,
        max_batch_events=1,
    )
    t1 = asyncio.create_task(producer.publish(_event("e-4a")))
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(producer.publish(_event("e-4b")))
    await asyncio.gather(t1, t2)
    assert producer.metrics.dropped_backpressure == 1
    assert len(client.primary) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_backpressure_strict_raises() -> None:
    client = _Client(sleep_on_send_sec=0.1)
    producer = SqsPersistenceTransportProducer(
        queue_url="q://primary",
        client=client,
        durability_mode="strict",
        max_attempts=2,
        backoff_base_ms=1,
        backoff_max_ms=1,
        backoff_jitter_fraction=0.0,
        max_inflight_events=1,
        max_batch_events=1,
    )
    t1 = asyncio.create_task(producer.publish(_event("e-5a")))
    await asyncio.sleep(0.01)
    with pytest.raises(PersistenceTransportBackpressureError):
        await producer.publish(_event("e-5b"))
    await t1
