"""Bulk admission envelope (L2 → expander). Master plan §4.4."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class BulkIntentV1(BaseModel):
    """One logical bulk after HTTP admission; count recipients share body and correlation ids."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[1] = Field(alias="schemaVersion", default=1)
    trace_id: str = Field(alias="traceId", min_length=1)
    batch_correlation_id: str = Field(alias="batchCorrelationId", min_length=1)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1)
    count: int = Field(ge=1)
    body: str = Field(min_length=1)
    received_at_ms: int = Field(alias="receivedAtMs", ge=0)
    metadata: dict[str, Any] | None = None
