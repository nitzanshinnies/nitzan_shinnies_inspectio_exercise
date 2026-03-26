"""Shared ingest types and shard routing (§16.4, §17)."""

from __future__ import annotations

from dataclasses import dataclass


class IngestUnavailableError(Exception):
    """Ingest boundary (SQS) unavailable or misconfigured."""


@dataclass(frozen=True, slots=True)
class IngestPutInput:
    """One logical message to admit to the FIFO queue."""

    message_id: str
    shard_id: int
    payload_body: str
    payload_to: str | None
    received_at_ms: int
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class IngestPutResult:
    """Result of a successful enqueue (per message)."""

    message_id: str
    shard_id: int
    ingest_sequence: str | None


def partition_key_for_shard(shard_id: int) -> str:
    """§16.4 / §17 — SQS FIFO `MessageGroupId` (fixed-width decimal)."""
    return f"{shard_id:05d}"
