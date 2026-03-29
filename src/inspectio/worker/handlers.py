"""SQS ingest handler: dedupe, journal, delete, `new_message`."""

from __future__ import annotations

import json
import logging

import redis.asyncio as redis

from inspectio.ingest.ingest_consumer import (
    append_ingest_template_a,
    try_claim_idempotency,
)
from inspectio.ingest.schema import MessageIngestedV1
from inspectio.ingest.sqs_fifo_consumer import RawSqsMessage
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
) -> tuple[bool, int | None]:
    """Apply ingest template A and schedule first send.

    Returns ``(delete_receipt, shard_to_flush)`` where ``shard_to_flush`` is set
    when ingest journal lines were appended (caller must flush that shard before
    SQS delete). ``None`` when there is nothing new to flush for this message.
    """
    data = json.loads(raw.body)
    ingested = MessageIngestedV1.model_validate(data)
    rt = scheduler_surface.require_runtime()
    # Shared SQS consumption: any worker may ingest any shard.
    # Shard ownership is still used for local snapshot partitioning.
    claim = await try_claim_idempotency(
        redis_client,
        settings,
        idempotency_key=ingested.idempotency_key,
        message_id=ingested.message_id,
    )
    if claim == "collision":
        log.error("idempotency collision for key=%s", ingested.idempotency_key)
        return True, None
    if claim == "duplicate_same":
        return True, None
    await append_ingest_template_a(writer, ingested)
    msg = rt.bootstrap_from_ingest(ingested)
    scheduler_surface.new_message(msg)
    return True, ingested.shard_id
