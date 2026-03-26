"""SQS ingest handler: dedupe, journal §18.3, delete, §25 `new_message`."""

from __future__ import annotations

import json
import logging

import redis.asyncio as redis

from inspectio.ingest.ingest_consumer import (
    append_ingest_template_a,
    try_claim_idempotency,
)
from inspectio.ingest.schema import MessageIngestedV1
from inspectio.ingest.sqs_fifo_consumer import RawSqsMessage, SqsFifoBatchFetcher
from inspectio.journal.writer import JournalWriter
from inspectio import scheduler_surface
from inspectio.settings import Settings

log = logging.getLogger("inspectio.worker.handlers")


async def process_raw_sqs_message(
    raw: RawSqsMessage,
    *,
    settings: Settings,
    writer: JournalWriter,
    redis_client: redis.Redis,
    fetcher: SqsFifoBatchFetcher,
) -> None:
    """Apply ingest template A, delete SQS, then schedule first send."""
    data = json.loads(raw.body)
    ingested = MessageIngestedV1.model_validate(data)
    rt = scheduler_surface.require_runtime()
    if not rt.owns_shard(ingested.shard_id):
        log.warning(
            "skip ingest shard not owned mid=%s shard=%s range=%s",
            ingested.message_id,
            ingested.shard_id,
            rt.owned_range,
        )
        return
    claim = await try_claim_idempotency(
        redis_client,
        settings,
        idempotency_key=ingested.idempotency_key,
        message_id=ingested.message_id,
    )
    if claim == "collision":
        log.error("idempotency collision for key=%s", ingested.idempotency_key)
        await fetcher.delete_message(raw.receipt_handle)
        return
    if claim == "duplicate_same":
        await fetcher.delete_message(raw.receipt_handle)
        return
    await append_ingest_template_a(writer, ingested)
    await fetcher.delete_message(raw.receipt_handle)
    msg = rt.bootstrap_from_ingest(ingested)
    scheduler_surface.new_message(msg)
