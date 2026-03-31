"""Idempotent replay reducer for persistence envelopes (P12.0)."""

from __future__ import annotations

from dataclasses import dataclass

from inspectio.v3.schemas.persistence_event import (
    EVENT_TYPE_ATTEMPT_RESULT,
    EVENT_TYPE_ENQUEUED,
    EVENT_TYPE_TERMINAL,
    TERMINAL_STATUS_PENDING,
    PersistenceEventV1,
    TerminalStatus,
)


@dataclass(slots=True)
class ReplayedMessageState:
    message_id: str
    attempt_count: int
    status: TerminalStatus
    next_due_at_ms: int | None
    received_at_ms: int


def fold_event(
    current: ReplayedMessageState | None,
    event: PersistenceEventV1,
) -> ReplayedMessageState | None:
    """Fold one event; terminal state is idempotent."""
    if event.message_id is None:
        return current

    if event.event_type == EVENT_TYPE_ENQUEUED:
        if current is not None:
            return current
        return ReplayedMessageState(
            message_id=event.message_id,
            attempt_count=0,
            status=TERMINAL_STATUS_PENDING,
            next_due_at_ms=event.received_at_ms,
            received_at_ms=int(event.received_at_ms or 0),
        )

    if current is None:
        # Replay can see attempt/terminal after dedupe; materialize minimal state.
        current = ReplayedMessageState(
            message_id=event.message_id,
            attempt_count=0,
            status=TERMINAL_STATUS_PENDING,
            next_due_at_ms=None,
            received_at_ms=int(event.received_at_ms or 0),
        )

    if current.status in ("success", "failed"):
        return current

    if event.event_type == EVENT_TYPE_ATTEMPT_RESULT:
        event_attempt = int(event.attempt_count or 0)
        if event_attempt > current.attempt_count:
            current.attempt_count = event_attempt
            current.next_due_at_ms = event.next_due_at_ms
        return current

    if event.event_type == EVENT_TYPE_TERMINAL:
        event_attempt = int(event.attempt_count or 0)
        if event_attempt > current.attempt_count:
            current.attempt_count = event_attempt
        if event.status in ("success", "failed"):
            current.status = event.status
            current.next_due_at_ms = None
    return current
