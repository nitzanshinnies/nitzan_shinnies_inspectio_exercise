"""Per-recipient send unit (expander → send worker). Master plan §4.4."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SendUnitV1(BaseModel):
    """One dequeued unit; attempts_completed is 0 before the first try_send on this unit."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[1] = Field(alias="schemaVersion", default=1)
    trace_id: str = Field(alias="traceId", min_length=1)
    message_id: str = Field(alias="messageId", min_length=1)
    body: str = Field(min_length=1)
    received_at_ms: int = Field(alias="receivedAtMs", ge=0)
    batch_correlation_id: str = Field(alias="batchCorrelationId", min_length=1)
    shard: int = Field(ge=0)
    attempts_completed: int = Field(alias="attemptsCompleted", default=0, ge=0, le=6)
