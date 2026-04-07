"""Unit tests for persistence transport SQS consumer ack path."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from inspectio.v3.persistence_transport.sqs_consumer import (
    SqsPersistenceTransportConsumer,
)
from inspectio.v3.schemas.persistence_event import PersistenceEventV1


class _FakeSqsClient:
    def __init__(self) -> None:
        self.delete_batches: list[list[dict[str, str]]] = []
        self.fail_next_batch = False
        self.inflight_delete_calls = 0
        self.max_inflight_delete_calls = 0

    async def delete_message_batch(  # noqa: D401, N803
        self, *, QueueUrl: str, Entries: list[dict[str, str]]
    ) -> dict[str, Any]:
        _ = QueueUrl
        self.inflight_delete_calls += 1
        self.max_inflight_delete_calls = max(
            self.max_inflight_delete_calls,
            self.inflight_delete_calls,
        )
        self.delete_batches.append(Entries)
        await asyncio.sleep(0.01)
        self.inflight_delete_calls -= 1
        if self.fail_next_batch:
            self.fail_next_batch = False
            return {"Successful": [], "Failed": [{"Id": Entries[0]["Id"]}]}
        return {"Successful": [{"Id": entry["Id"]} for entry in Entries], "Failed": []}


def _event(event_id: str) -> PersistenceEventV1:
    return PersistenceEventV1.model_validate(
        {
            "schemaVersion": 1,
            "eventId": event_id,
            "eventType": "attempt_result",
            "emittedAtMs": 1_700_000_000_000,
            "shard": 0,
            "segmentSeq": 1,
            "segmentEventIndex": 0,
            "traceId": "t",
            "batchCorrelationId": "b",
            "messageId": "m",
            "receivedAtMs": 1_700_000_000_000,
            "attemptCount": 1,
            "attemptOk": True,
            "status": "pending",
            "nextDueAtMs": 1_700_000_000_100,
        },
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ack_many_batches_delete_requests_in_tens() -> None:
    client = _FakeSqsClient()
    consumer = SqsPersistenceTransportConsumer(
        client=client,
        queue_url="q://persist",
        wait_seconds=20,
        receive_max_events=10,
    )
    events = [_event(f"e-{i}") for i in range(23)]
    for event in events:
        consumer._receipt_by_event_id[event.event_id] = f"rh-{event.event_id}"  # noqa: SLF001
    await consumer.ack_many(events)
    assert [len(batch) for batch in client.delete_batches] == [10, 10, 3]
    assert consumer._receipt_by_event_id == {}  # noqa: SLF001


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ack_many_keeps_receipts_when_batch_delete_fails() -> None:
    client = _FakeSqsClient()
    client.fail_next_batch = True
    consumer = SqsPersistenceTransportConsumer(
        client=client,
        queue_url="q://persist",
        wait_seconds=20,
        receive_max_events=10,
    )
    event = _event("e-fail")
    consumer._receipt_by_event_id[event.event_id] = "rh-fail"  # noqa: SLF001
    with pytest.raises(RuntimeError, match="delete_message_batch failed"):
        await consumer.ack_many([event])
    assert consumer._receipt_by_event_id[event.event_id] == "rh-fail"  # noqa: SLF001


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ack_many_respects_bounded_delete_concurrency() -> None:
    client = _FakeSqsClient()
    consumer = SqsPersistenceTransportConsumer(
        client=client,
        queue_url="q://persist",
        wait_seconds=20,
        receive_max_events=10,
        ack_delete_max_concurrency=2,
    )
    events = [_event(f"e-{i}") for i in range(50)]
    for event in events:
        consumer._receipt_by_event_id[event.event_id] = f"rh-{event.event_id}"  # noqa: SLF001
    await consumer.ack_many(events)
    assert client.max_inflight_delete_calls <= 2
    assert client.max_inflight_delete_calls >= 1
