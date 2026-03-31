"""Checkpoint contracts for deterministic persistence replay (P12.0)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PERSISTENCE_CHECKPOINT_SCHEMA_VERSION = 1


class PersistenceCheckpointV1(BaseModel):
    """Per-shard replay checkpoint; segment write must precede checkpoint advance."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[1] = Field(
        alias="schemaVersion",
        default=PERSISTENCE_CHECKPOINT_SCHEMA_VERSION,
    )
    shard: int = Field(ge=0)
    last_segment_seq: int = Field(alias="lastSegmentSeq", ge=0)
    next_segment_seq: int = Field(alias="nextSegmentSeq", ge=1)
    last_event_index: int = Field(alias="lastEventIndex", ge=0)
    updated_at_ms: int = Field(alias="updatedAtMs", ge=0)
    segment_object_key: str = Field(alias="segmentObjectKey", min_length=1)

    @model_validator(mode="after")
    def _next_seq_follows_last(self) -> PersistenceCheckpointV1:
        expected = self.last_segment_seq + 1
        if self.next_segment_seq != expected:
            msg = f"nextSegmentSeq must equal lastSegmentSeq + 1 ({expected})"
            raise ValueError(msg)
        return self
