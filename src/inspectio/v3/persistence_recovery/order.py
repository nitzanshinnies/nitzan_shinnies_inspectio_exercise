"""Deterministic ordering for replay ingestion (P12.0)."""

from __future__ import annotations

from collections.abc import Iterable

from inspectio.v3.schemas.persistence_event import PersistenceEventV1


def sorted_for_replay(
    events: Iterable[PersistenceEventV1],
) -> list[PersistenceEventV1]:
    """Stable total order from possibly unordered transport delivery."""
    return sorted(
        events,
        key=lambda e: (
            e.shard,
            e.segment_seq,
            e.segment_event_index,
            e.emitted_at_ms,
            e.event_id,
        ),
    )
