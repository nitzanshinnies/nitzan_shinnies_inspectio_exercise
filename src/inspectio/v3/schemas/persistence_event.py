"""Persistence event envelope contracts (P12.0).

Decision record lock (P12.0):
- Durability mode: best_effort (default-safe baseline, drops must be counted later).
- Transport: queue-based async handoff; ordering comes from segment metadata.
- Checkpoint contract: segment object write succeeds before checkpoint advance.
- Replay conflicts: idempotent fold; highest attempt_count wins before terminal.
- Backpressure: bounded transport buffers with explicit lag metrics (P12.2+).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EVENT_TYPE_ATTEMPT_RESULT = "attempt_result"
EVENT_TYPE_ENQUEUED = "enqueued"
EVENT_TYPE_TERMINAL = "terminal"
PERSISTENCE_EVENT_SCHEMA_VERSION = 1
TERMINAL_STATUS_FAILED = "failed"
TERMINAL_STATUS_PENDING = "pending"
TERMINAL_STATUS_SUCCESS = "success"

PersistenceEventType = Literal[
    EVENT_TYPE_ATTEMPT_RESULT,
    EVENT_TYPE_ENQUEUED,
    EVENT_TYPE_TERMINAL,
]
TerminalStatus = Literal[
    TERMINAL_STATUS_FAILED,
    TERMINAL_STATUS_PENDING,
    TERMINAL_STATUS_SUCCESS,
]


class PersistenceEventV1(BaseModel):
    """Versioned envelope used by durability transport and replay."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[1] = Field(
        alias="schemaVersion",
        default=PERSISTENCE_EVENT_SCHEMA_VERSION,
    )
    event_id: str = Field(alias="eventId", min_length=1)
    event_type: PersistenceEventType = Field(alias="eventType")
    emitted_at_ms: int = Field(alias="emittedAtMs", ge=0)
    shard: int = Field(ge=0)
    segment_seq: int = Field(alias="segmentSeq", ge=0)
    segment_event_index: int = Field(alias="segmentEventIndex", ge=0)

    trace_id: str = Field(alias="traceId", min_length=1)
    batch_correlation_id: str = Field(alias="batchCorrelationId", min_length=1)
    message_id: str | None = Field(alias="messageId", default=None, min_length=1)

    # Shared lifecycle fields.
    attempt_count: int | None = Field(alias="attemptCount", default=None, ge=0, le=6)
    status: TerminalStatus | None = Field(alias="status", default=None)
    reason: str | None = None

    # Enqueue payload.
    received_at_ms: int | None = Field(alias="receivedAtMs", default=None, ge=0)
    count: int | None = Field(default=None, ge=1)
    body: str | None = Field(default=None, min_length=1)

    # Attempt payload.
    attempt_ok: bool | None = Field(alias="attemptOk", default=None)
    next_due_at_ms: int | None = Field(alias="nextDueAtMs", default=None, ge=0)

    # Terminal payload.
    final_timestamp_ms: int | None = Field(alias="finalTimestampMs", default=None, ge=0)

    @model_validator(mode="after")
    def _validate_event_shape(self) -> PersistenceEventV1:
        if self.event_type == EVENT_TYPE_ENQUEUED:
            self._require(self.received_at_ms is not None, "receivedAtMs required")
            self._require(self.count is not None, "count required")
            self._require(self.body is not None, "body required")
            self._require(
                self.attempt_count in (None, 0), "attemptCount must be 0|null"
            )
            self._require(
                self.status in (None, TERMINAL_STATUS_PENDING),
                "status must be pending|null",
            )
            return self

        if self.event_type == EVENT_TYPE_ATTEMPT_RESULT:
            self._require(self.message_id is not None, "messageId required")
            self._require(
                self.attempt_count is not None and self.attempt_count >= 1,
                "attemptCount >= 1 required",
            )
            self._require(self.attempt_ok is not None, "attemptOk required")
            if self.attempt_ok:
                self._require(
                    self.status
                    in (None, TERMINAL_STATUS_PENDING, TERMINAL_STATUS_SUCCESS),
                    "status for ok attempt must be pending|success|null",
                )
            else:
                self._require(
                    self.next_due_at_ms is not None
                    or self.status == TERMINAL_STATUS_FAILED,
                    "failed attempt requires nextDueAtMs or status=failed",
                )
            return self

        # terminal
        self._require(self.message_id is not None, "messageId required")
        self._require(
            self.attempt_count is not None and self.attempt_count >= 1,
            "attemptCount >= 1 required",
        )
        self._require(self.final_timestamp_ms is not None, "finalTimestampMs required")
        self._require(
            self.status in (TERMINAL_STATUS_SUCCESS, TERMINAL_STATUS_FAILED),
            "terminal status must be success|failed",
        )
        if self.status == TERMINAL_STATUS_SUCCESS:
            self._require(
                self.reason in (None, ""), "success terminal reason must be empty|null"
            )
        else:
            self._require(bool(self.reason), "failed terminal reason required")
        return self

    @staticmethod
    def _require(ok: bool, msg: str) -> None:
        if not ok:
            raise ValueError(msg)
