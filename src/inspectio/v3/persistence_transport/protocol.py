"""Transport producer/consumer contracts for persistence events (P12.2)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from inspectio.v3.schemas.persistence_event import PersistenceEventV1


@runtime_checkable
class PersistenceTransportProducer(Protocol):
    async def publish(self, event: PersistenceEventV1) -> None:
        """Publish one event to durability transport."""

    async def publish_many(self, events: Sequence[PersistenceEventV1]) -> None:
        """Publish a batch (producer may split by transport limits)."""


@runtime_checkable
class PersistenceTransportConsumer(Protocol):
    async def receive_many(self, *, max_events: int) -> list[PersistenceEventV1]:
        """Read up to `max_events` from transport."""

    async def ack_many(self, events: Sequence[PersistenceEventV1]) -> None:
        """Acknowledge consumed events."""
