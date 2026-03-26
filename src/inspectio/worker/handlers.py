"""Worker ingest handlers for P5 (dedupe + journal template A only)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import redis.asyncio as redis

from inspectio.ingest.schema import MessageIngestedV1
from inspectio.perf_log import perf_line
from inspectio.journal.records import JournalRecordV1
from inspectio.models import Message
from inspectio.worker.runtime import InMemorySchedulerRuntime

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
        self,
        *,
        idempotency_store: IdempotencyStore,
        idempotency_ttl_sec: int,
        runtime: InMemorySchedulerRuntime | None = None,
    ) -> None:
        self._idempotency_store = idempotency_store
        self._idempotency_ttl_sec = idempotency_ttl_sec
        self._runtime = runtime

    async def apply_ingest(
        self,
        *,
        message: MessageIngestedV1,
        next_record_index: Callable[[], int],
        now_ms: int,
    ) -> list[JournalRecordV1]:
        key = f"{IDEMPOTENCY_KEY_PREFIX}{message.idempotency_key}"
        r0 = time.monotonic_ns()
        accepted = await self._idempotency_store.set_nx(
            key=key,
            value=message.message_id,
            ttl_sec=self._idempotency_ttl_sec,
        )
        redis_ms = (time.monotonic_ns() - r0) / 1_000_000
        if not accepted:
            perf_line(
                "ingest_handler",
                message_id=message.message_id,
                shard_id=message.shard_id,
                duplicate=1,
                redis_set_nx_ms=f"{redis_ms:.3f}",
            )
            return []

        t_build0 = time.monotonic_ns()
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
        records = [ingest_applied, dispatch_scheduled]
        template_ms = (time.monotonic_ns() - t_build0) / 1_000_000
        if self._runtime is None:
            perf_line(
                "ingest_handler",
                message_id=message.message_id,
                shard_id=message.shard_id,
                duplicate=0,
                redis_set_nx_ms=f"{redis_ms:.3f}",
                journal_template_ms=f"{template_ms:.3f}",
                runtime_new_message_ms="0.000",
            )
            return records
        start = self._runtime.journal_length()
        rt0 = time.monotonic_ns()
        await self._runtime.new_message(
            Message(
                message_id=message.message_id,
                to=message.payload.to or "",
                body=message.payload.body,
            ),
            shard_id=message.shard_id,
        )
        runtime_ms = (time.monotonic_ns() - rt0) / 1_000_000
        perf_line(
            "ingest_handler",
            message_id=message.message_id,
            shard_id=message.shard_id,
            duplicate=0,
            redis_set_nx_ms=f"{redis_ms:.3f}",
            journal_template_ms=f"{template_ms:.3f}",
            runtime_new_message_ms=f"{runtime_ms:.3f}",
        )
        runtime_records = self._runtime.journal_since(start)
        reindexed_runtime_records = [
            line.model_copy(update={"record_index": next_record_index()})
            for line in runtime_records
        ]
        self._runtime.journal[start:] = reindexed_runtime_records
        return records + reindexed_runtime_records


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


async def apply_ingest_to_runtime(
    *,
    runtime: InMemorySchedulerRuntime,
    message: MessageIngestedV1,
) -> None:
    """Bridge ingest message to scheduler runtime start (P6 integration step)."""
    await runtime.new_message(
        Message(
            message_id=message.message_id,
            to=message.payload.to or "",
            body=message.payload.body,
        )
    )
