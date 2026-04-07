"""Transport-backed persistence emitter (P12.2)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from inspectio.v3.persistence_emitter.enqueued_outbound import (
    L2EnqueuedPersistenceOutboundQueue,
)
from inspectio.v3.persistence_emitter.protocol import PersistenceEventEmitter
from inspectio.v3.persistence_transport.protocol import PersistenceTransportProducer
from inspectio.v3.persistence_transport.sharded_router import (
    ShardedPersistenceTransportProducer,
)
from inspectio.v3.persistence_transport.sqs_producer import (
    SqsPersistenceTransportProducer,
)
from inspectio.v3.schemas.persistence_event import (
    EVENT_TYPE_ATTEMPT_RESULT,
    EVENT_TYPE_ENQUEUED,
    EVENT_TYPE_TERMINAL,
    PersistenceEventV1,
)


class TransportPersistenceEventEmitter(PersistenceEventEmitter):
    """Builds event envelopes and hands off to async transport producer."""

    def __init__(
        self,
        *,
        producer: PersistenceTransportProducer,
        clock_ms: Callable[[], int],
        enqueued_outbound: L2EnqueuedPersistenceOutboundQueue | None = None,
    ) -> None:
        self._producer = producer
        self._clock_ms = clock_ms
        self._enqueued_outbound = enqueued_outbound
        self._next_seq_by_shard: dict[int, int] = {}

    async def persistence_transport_observability_snapshot(self) -> dict[str, Any]:
        """Snapshot of underlying transport producer(s) (in-process)."""
        producer = self._producer
        if isinstance(producer, ShardedPersistenceTransportProducer):
            inner = await producer.observability_snapshot()
        elif isinstance(producer, SqsPersistenceTransportProducer):
            inner = await producer.observability_snapshot()
        else:
            inner = {
                "kind": "unknown_persistence_transport_producer",
                "type": type(producer).__name__,
            }
        return {"persistence_transport": inner}

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
        event = self._event(
            event_type=EVENT_TYPE_ENQUEUED,
            trace_id=trace_id,
            batch_correlation_id=batch_correlation_id,
            shard=shard,
            message_id=None,
            count=count,
            body=body,
            received_at_ms=received_at_ms,
            attempt_count=0,
            status="pending",
        )
        outbound = self._enqueued_outbound
        if outbound is not None:
            outbound.put_nowait(event)
            return
        await self._producer.publish(event)

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
        event = self._event(
            event_type=EVENT_TYPE_ATTEMPT_RESULT,
            trace_id=trace_id,
            batch_correlation_id=batch_correlation_id,
            shard=shard,
            message_id=message_id,
            body=body,
            received_at_ms=received_at_ms,
            attempt_count=attempt_count,
            attempt_ok=attempt_ok,
            status=status,
            next_due_at_ms=next_due_at_ms,
        )
        await self._producer.publish(event)

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
        event = self._event(
            event_type=EVENT_TYPE_TERMINAL,
            trace_id=trace_id,
            batch_correlation_id=batch_correlation_id,
            shard=shard,
            message_id=message_id,
            body=body,
            received_at_ms=received_at_ms,
            attempt_count=attempt_count,
            status=status,
            final_timestamp_ms=final_timestamp_ms,
            reason=reason,
        )
        await self._producer.publish(event)

    def _event(
        self,
        *,
        event_type: str,
        trace_id: str,
        batch_correlation_id: str,
        shard: int,
        message_id: str | None,
        count: int | None = None,
        body: str | None = None,
        received_at_ms: int | None = None,
        attempt_count: int | None = None,
        attempt_ok: bool | None = None,
        status: str | None = None,
        next_due_at_ms: int | None = None,
        final_timestamp_ms: int | None = None,
        reason: str | None = None,
    ) -> PersistenceEventV1:
        segment_seq = self._next_seq_by_shard.get(shard, 0)
        self._next_seq_by_shard[shard] = segment_seq + 1
        return PersistenceEventV1(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            emitted_at_ms=self._clock_ms(),
            shard=shard,
            segment_seq=segment_seq,
            segment_event_index=0,
            trace_id=trace_id,
            batch_correlation_id=batch_correlation_id,
            message_id=message_id,
            count=count,
            body=body,
            received_at_ms=received_at_ms,
            attempt_count=attempt_count,
            attempt_ok=attempt_ok,
            status=status,
            next_due_at_ms=next_due_at_ms,
            final_timestamp_ms=final_timestamp_ms,
            reason=reason,
        )
