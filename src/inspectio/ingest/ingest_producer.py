"""Shared types for admission ingest (SQS FIFO replaces Kinesis PutRecords)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class IngestUnavailableError(RuntimeError):
    """Raised when ingest queue is unavailable."""


class IngestBufferOverflowError(RuntimeError):
    """Raised when in-memory ingest policy must reject requests."""


@dataclass(frozen=True, slots=True)
class IngestPutInput:
    """Input row for an ingest enqueue."""

    idempotency_key: str
    message_id: str
    payload_body: str
    payload_to: str
    received_at_ms: int
    shard_id: int


@dataclass(frozen=True, slots=True)
class IngestPutResult:
    """Per-message write result returned to route layer."""

    message_id: str
    shard_id: int
    ingest_sequence: str | None


PARTITION_KEY_WIDTH = 5


def partition_key_for_shard(shard_id: int) -> str:
    """Return FIFO MessageGroupId / legacy partition key (TC-STR-003)."""
    return f"{shard_id:0{PARTITION_KEY_WIDTH}d}"


class IngestProducer(Protocol):
    """Route-facing producer contract for dependency injection."""

    async def put_messages(
        self, messages: list[IngestPutInput]
    ) -> list[IngestPutResult]:
        """Write one or more ingest records and return per-record result."""
