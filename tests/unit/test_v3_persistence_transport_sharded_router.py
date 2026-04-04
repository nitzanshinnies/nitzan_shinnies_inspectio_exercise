"""P12.8: shard-aware persistence producer router tests."""

from __future__ import annotations

from typing import Any

import pytest

from inspectio.v3.persistence_transport.sharded_router import (
    ShardedPersistenceTransportProducer,
)
from inspectio.v3.schemas.persistence_event import PersistenceEventV1


class _ProducerSpy:
    def __init__(self) -> None:
        self.published_ids: list[str] = []

    async def publish(self, event: PersistenceEventV1) -> None:
        self.published_ids.append(event.event_id)

    async def publish_many(self, events: list[PersistenceEventV1]) -> None:
        self.published_ids.extend([event.event_id for event in events])


def _event(*, event_id: str, shard: int) -> PersistenceEventV1:
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "eventId": event_id,
        "eventType": "attempt_result",
        "emittedAtMs": 1_700_000_000_000,
        "shard": shard,
        "segmentSeq": 1,
        "segmentEventIndex": 0,
        "traceId": "t",
        "batchCorrelationId": "b",
        "messageId": "m",
        "receivedAtMs": 1_700_000_000_000,
        "attemptCount": 1,
        "attemptOk": True,
        "status": "pending",
        "nextDueAtMs": 1_700_000_000_500,
    }
    return PersistenceEventV1.model_validate(payload)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sharded_router_routes_events_to_matching_shard_producer() -> None:
    p0 = _ProducerSpy()
    p1 = _ProducerSpy()
    router = ShardedPersistenceTransportProducer(producers_by_shard={0: p0, 1: p1})
    await router.publish_many(
        [
            _event(event_id="e-0", shard=0),
            _event(event_id="e-1", shard=1),
            _event(event_id="e-2", shard=0),
        ]
    )
    assert p0.published_ids == ["e-0", "e-2"]
    assert p1.published_ids == ["e-1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sharded_router_rejects_missing_shard_binding() -> None:
    router = ShardedPersistenceTransportProducer(producers_by_shard={0: _ProducerSpy()})
    with pytest.raises(ValueError, match="no persistence producer for shard 1"):
        await router.publish(_event(event_id="missing", shard=1))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sharded_observability_marks_unknown_producer_type() -> None:
    router = ShardedPersistenceTransportProducer(producers_by_shard={0: _ProducerSpy()})
    snap = await router.observability_snapshot()
    assert snap["kind"] == "sharded_persistence_transport_producer"
    assert snap["shards"]["0"]["error"] == "unsupported_producer_type"
