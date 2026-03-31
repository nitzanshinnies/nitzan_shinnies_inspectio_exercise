"""Persistence event emitter abstraction (P12.1)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PersistenceEventEmitter(Protocol):
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
        """Emit lifecycle event when one BulkIntent enters scheduler flow."""

    async def emit_attempt_result(
        self,
        *,
        trace_id: str,
        batch_correlation_id: str,
        message_id: str,
        shard: int,
        received_at_ms: int,
        attempt_count: int,
        attempt_ok: bool,
        status: str,
        next_due_at_ms: int | None,
    ) -> None:
        """Emit per-attempt outcome event (success/failure, before terminal finalize)."""

    async def emit_terminal(
        self,
        *,
        trace_id: str,
        batch_correlation_id: str,
        message_id: str,
        shard: int,
        received_at_ms: int,
        attempt_count: int,
        status: str,
        final_timestamp_ms: int,
        reason: str | None,
    ) -> None:
        """Emit final terminal lifecycle event."""
