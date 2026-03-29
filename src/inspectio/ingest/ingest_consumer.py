"""Ingest journal template A + idempotency helpers (§17.4, §29.7)."""

from __future__ import annotations

import time
from typing import Literal

import redis.asyncio as redis

from inspectio.ingest.schema import MessageIngestedV1, body_hash_for_text
from inspectio.journal.writer import JournalWriter
from inspectio.settings import Settings


def idempotency_redis_key(idempotency_key: str) -> str:
    return f"inspectio:idempotency:{idempotency_key}"


async def try_claim_idempotency(
    r: redis.Redis,
    settings: Settings,
    *,
    idempotency_key: str,
    message_id: str,
) -> Literal["new", "duplicate_same", "collision"]:
    """`SET NX` idempotency mapping; duplicate SQS delivery returns duplicate_same."""
    key = idempotency_redis_key(idempotency_key)
    ttl = settings.idempotency_ttl_sec
    ok = await r.set(key, message_id, nx=True, ex=ttl)
    if ok:
        return "new"
    existing = await r.get(key)
    if existing is None:
        return "new"
    existing_s = (
        existing.decode("utf-8")
        if isinstance(existing, (bytes, bytearray))
        else str(existing)
    )
    if existing_s == message_id:
        return "duplicate_same"
    return "collision"


async def append_ingest_template_a(
    writer: JournalWriter,
    ingested: MessageIngestedV1,
) -> None:
    """Append `INGEST_APPLIED` then `DISPATCH_SCHEDULED` (reason immediate).

    Does **not** flush: the SQS consumer flushes affected shards once per receive
    batch before `DeleteMessage` (§18.3 durability without one PUT per message).
    """
    now = int(time.time() * 1000)
    bh = body_hash_for_text(ingested.payload.body)
    r1 = await writer.build_record(
        ingested.shard_id,
        record_type="INGEST_APPLIED",
        message_id=ingested.message_id,
        ts_ms=now,
        payload={
            "receivedAtMs": ingested.received_at_ms,
            "idempotencyKey": ingested.idempotency_key,
            "bodyHash": bh,
        },
    )
    await writer.append_record(r1)
    r2 = await writer.build_record(
        ingested.shard_id,
        record_type="DISPATCH_SCHEDULED",
        message_id=ingested.message_id,
        ts_ms=now,
        payload={"reason": "immediate"},
    )
    await writer.append_record(r2)
