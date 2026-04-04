"""L2 runtime dependencies (clock, enqueue, idempotency, sharding)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from inspectio.v3.l2.enqueue_port import BulkEnqueuePort
from inspectio.v3.l2.idempotency import InMemoryIdempotencyStore
from inspectio.v3.outcomes.protocol import OutcomesReadPort
from inspectio.v3.persistence_emitter.protocol import PersistenceEventEmitter


@dataclass(frozen=True, slots=True)
class L2Dependencies:
    clock_ms: Callable[[], int]
    enqueue_backend: BulkEnqueuePort
    idempotency: InMemoryIdempotencyStore
    outcomes_reader: OutcomesReadPort
    persistence_emitter: PersistenceEventEmitter
    shard_count: int
    expose_persistence_transport_metrics: bool = False
