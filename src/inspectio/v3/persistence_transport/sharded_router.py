"""Shard-aware persistence producer router (P12.8)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from inspectio.v3.persistence_transport.protocol import PersistenceTransportProducer
from inspectio.v3.persistence_transport.sqs_producer import (
    SqsPersistenceTransportProducer,
)
from inspectio.v3.schemas.persistence_event import PersistenceEventV1


class ShardedPersistenceTransportProducer(PersistenceTransportProducer):
    """Routes events by event.shard to the matching producer."""

    def __init__(
        self, *, producers_by_shard: dict[int, PersistenceTransportProducer]
    ) -> None:
        if not producers_by_shard:
            raise ValueError("producers_by_shard must not be empty")
        self._producers_by_shard = dict(producers_by_shard)

    async def observability_snapshot(self) -> dict[str, Any]:
        """Per-shard snapshots when underlying producers are SQS producers."""
        shards: dict[str, Any] = {}
        for shard_id in sorted(self._producers_by_shard):
            producer = self._producers_by_shard[shard_id]
            if isinstance(producer, SqsPersistenceTransportProducer):
                shards[str(shard_id)] = await producer.observability_snapshot()
            else:
                shards[str(shard_id)] = {
                    "error": "unsupported_producer_type",
                    "type": type(producer).__name__,
                }
        return {"kind": "sharded_persistence_transport_producer", "shards": shards}

    async def publish(self, event: PersistenceEventV1) -> None:
        producer = self._producers_by_shard.get(event.shard)
        if producer is None:
            raise ValueError(f"no persistence producer for shard {event.shard}")
        await producer.publish(event)

    async def publish_many(self, events: Sequence[PersistenceEventV1]) -> None:
        if not events:
            return
        grouped: dict[int, list[PersistenceEventV1]] = {}
        for event in events:
            grouped.setdefault(event.shard, []).append(event)
        for shard, shard_events in grouped.items():
            producer = self._producers_by_shard.get(shard)
            if producer is None:
                raise ValueError(f"no persistence producer for shard {shard}")
            await producer.publish_many(shard_events)
