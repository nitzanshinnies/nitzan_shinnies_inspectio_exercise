"""No-op persistence emitter (default-safe baseline for P12.1)."""

from __future__ import annotations

from inspectio.v3.persistence_emitter.protocol import PersistenceEventEmitter


class NoopPersistenceEventEmitter(PersistenceEventEmitter):
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
        return None

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
        return None

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
        return None
