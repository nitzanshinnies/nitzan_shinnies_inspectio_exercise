"""Receive BulkIntentV1 from bulk queue, fan out, delete (P3)."""

from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

from inspectio.v3.expander.dedupe import ExpandedBulkDedupe
from inspectio.v3.expander.fanout import bulk_to_send_units
from inspectio.v3.expander.metrics import ExpansionMetrics
from inspectio.v3.expander.publish import publish_send_units_to_shards
from inspectio.v3.schemas.bulk_intent import BulkIntentV1

_log = logging.getLogger(__name__)


async def expand_one_bulk_message(
    client: Any,
    *,
    message: dict[str, str],
    bulk_queue_url: str,
    dedupe: ExpandedBulkDedupe,
    send_queue_urls: list[str],
    metrics: ExpansionMetrics,
    sleeper: Callable[[float], Awaitable[None]],
    rng: random.Random,
    max_publish_attempts: int = 6,
) -> None:
    """Parse bulk, publish units to send shards, then delete bulk message.

    If ``MessageId`` was already expanded (redelivery after successful publish), only delete.
    """
    mid = message["MessageId"]
    receipt = message["ReceiptHandle"]
    raw_body = message["Body"]

    if dedupe.is_expanded(mid):
        await client.delete_message(QueueUrl=bulk_queue_url, ReceiptHandle=receipt)
        return

    bulk = BulkIntentV1.model_validate_json(raw_body)
    units = bulk_to_send_units(bulk, shard_count=len(send_queue_urls))
    for u in units:
        _log.info(
            "expander_unit trace=%s batch=%s messageId=%s shard=%s",
            bulk.trace_id,
            bulk.batch_correlation_id,
            u.message_id,
            u.shard,
        )

    await publish_send_units_to_shards(
        client,
        units=units,
        send_queue_urls=send_queue_urls,
        max_attempts=max_publish_attempts,
        sleeper=sleeper,
        rng=rng,
        metrics=metrics,
    )
    dedupe.mark_expanded(mid)
    await client.delete_message(QueueUrl=bulk_queue_url, ReceiptHandle=receipt)


async def receive_and_expand_once(
    client: Any,
    *,
    bulk_queue_url: str,
    wait_seconds: int,
    visibility_timeout_seconds: int,
    dedupe: ExpandedBulkDedupe,
    send_queue_urls: list[str],
    metrics: ExpansionMetrics,
    sleeper: Callable[[float], Awaitable[None]],
    rng: random.Random,
    max_publish_attempts: int = 6,
) -> bool:
    """Long-poll once; expand at most one bulk. Returns True if a message was handled."""
    resp = await client.receive_message(
        QueueUrl=bulk_queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=wait_seconds,
        VisibilityTimeout=visibility_timeout_seconds,
    )
    msgs = resp.get("Messages", [])
    if not msgs:
        return False
    await expand_one_bulk_message(
        client,
        message=msgs[0],
        bulk_queue_url=bulk_queue_url,
        dedupe=dedupe,
        send_queue_urls=send_queue_urls,
        metrics=metrics,
        sleeper=sleeper,
        rng=rng,
        max_publish_attempts=max_publish_attempts,
    )
    return True
