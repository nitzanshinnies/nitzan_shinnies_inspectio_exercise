"""Worker ingest handlers for P5 (dedupe + journal template A only)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

import redis.asyncio as redis

from inspectio.ingest.schema import MessageIngestedV1
from inspectio.journal.records import JournalRecordV1

IDEMPOTENCY_KEY_PREFIX = "inspectio:idempotency:"
DISPATCH_REASON_IMMEDIATE = "immediate"


class IdempotencyStore(Protocol):
    """Minimal Redis-like interface for SET NX TTL semantics."""

    async def set_nx(self, *, key: str, value: str, ttl_sec: int) -> bool:
        """Return True only for first-seen key."""


@dataclass(frozen=True, slots=True)
class IngestApplyResult:
    """Outcome of applying one ingest message in worker handler."""

    applied: bool
    journal_records: list[JournalRecordV1]


class IngestJournalHandler:
    """Apply ingest events to journal lines (template A) with idempotency."""

    def __init__(
        self, *, idempotency_store: IdempotencyStore, idempotency_ttl_sec: int
    ) -> None:
        self._idempotency_store = idempotency_store
        self._idempotency_ttl_sec = idempotency_ttl_sec

    async def apply_ingest(
        self,
        *,
        message: MessageIngestedV1,
        next_record_index: Callable[[], int],
        now_ms: int,
    ) -> list[JournalRecordV1]:
        key = f"{IDEMPOTENCY_KEY_PREFIX}{message.idempotency_key}"
        accepted = await self._idempotency_store.set_nx(
            key=key,
            value=message.message_id,
            ttl_sec=self._idempotency_ttl_sec,
        )
        if not accepted:
            return []

        ingest_applied = JournalRecordV1.model_validate(
            {
                "v": 1,
                "type": "INGEST_APPLIED",
                "shardId": message.shard_id,
                "messageId": message.message_id,
                "tsMs": now_ms,
                "recordIndex": next_record_index(),
                "payload": {
                    "receivedAtMs": message.received_at_ms,
                    "idempotencyKey": message.idempotency_key,
                    "bodyHash": message.body_hash,
                },
            }
        )
        dispatch_scheduled = JournalRecordV1.model_validate(
            {
                "v": 1,
                "type": "DISPATCH_SCHEDULED",
                "shardId": message.shard_id,
                "messageId": message.message_id,
                "tsMs": now_ms,
                "recordIndex": next_record_index(),
                "payload": {"reason": DISPATCH_REASON_IMMEDIATE},
            }
        )
        return [ingest_applied, dispatch_scheduled]


class RedisIdempotencyStore:
    """Redis-backed idempotency store using SET NX with TTL (§17.4)."""

    def __init__(self, *, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def set_nx(self, *, key: str, value: str, ttl_sec: int) -> bool:
        result = await self._redis.set(name=key, value=value, ex=ttl_sec, nx=True)
        return bool(result)


def replay_pending_from_journal_lines(
    lines: list[JournalRecordV1],
) -> dict[str, dict[str, Any]]:
    """Synthetic replay baseline for TC-REC-001 pending state checks."""
    by_message: dict[str, dict[str, Any]] = {}
    ingest_received_at_ms: dict[str, int] = {}
    for line in lines:
        if line.type == "INGEST_APPLIED":
            ingest_received_at_ms[line.message_id] = int(line.payload["receivedAtMs"])
            continue
        if line.type != "DISPATCH_SCHEDULED":
            continue
        if line.message_id not in ingest_received_at_ms:
            continue
        by_message[line.message_id] = {
            "attemptCount": 0,
            "nextDueAtMs": ingest_received_at_ms[line.message_id],
            "status": "pending",
        }
    return by_message
