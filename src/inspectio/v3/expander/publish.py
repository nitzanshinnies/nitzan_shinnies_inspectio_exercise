"""Publish SendUnitV1 to sharded standard SQS queues (SendMessageBatch, P3)."""

from __future__ import annotations

import json
import random
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from botocore.exceptions import ClientError

from inspectio.v3.expander.fanout import chunk_fixed_size
from inspectio.v3.expander.metrics import ExpansionMetrics
from inspectio.v3.schemas.send_unit import SendUnitV1
from inspectio.v3.sqs.aws_throttle import is_aws_throttle_error
from inspectio.v3.sqs.backoff import compute_backoff_delay_ms

_BATCH_FAIL_RETRY_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "RequestThrottled",
        "SlowDown",
        "ServiceUnavailable",
    },
)


async def publish_send_units_to_shards(
    client: Any,
    *,
    units: list[SendUnitV1],
    send_queue_urls: list[str],
    max_attempts: int,
    sleeper: Callable[[float], Awaitable[None]],
    rng: random.Random,
    metrics: ExpansionMetrics,
) -> None:
    """Group by ``unit.shard``, then ``SendMessageBatch`` (max 10 entries) per queue."""
    k = len(send_queue_urls)
    by_shard: dict[int, list[SendUnitV1]] = defaultdict(list)
    for u in units:
        if u.shard < 0 or u.shard >= k:
            msg = f"shard {u.shard} out of range for K={k}"
            raise ValueError(msg)
        by_shard[u.shard].append(u)

    for shard_idx in sorted(by_shard.keys()):
        url = send_queue_urls[shard_idx]
        for chunk in chunk_fixed_size(by_shard[shard_idx], 10):
            await _send_message_batch_with_retries(
                client,
                queue_url=url,
                units=chunk,
                max_attempts=max_attempts,
                sleeper=sleeper,
                rng=rng,
                metrics=metrics,
            )
            metrics.expanded_units_published += len(chunk)


async def _send_message_batch_with_retries(
    client: Any,
    *,
    queue_url: str,
    units: list[SendUnitV1],
    max_attempts: int,
    sleeper: Callable[[float], Awaitable[None]],
    rng: random.Random,
    metrics: ExpansionMetrics,
) -> None:
    pending = _batch_entries_from_units(units)
    for attempt in range(max_attempts):
        try:
            resp = await client.send_message_batch(QueueUrl=queue_url, Entries=pending)
        except ClientError as exc:
            if not is_aws_throttle_error(exc) or attempt + 1 >= max_attempts:
                raise
            metrics.send_batch_throttle_retries += 1
            delay_ms = compute_backoff_delay_ms(attempt, rng=rng)
            await sleeper(delay_ms / 1000.0)
            continue

        failed = resp.get("Failed", [])
        if not failed:
            return

        if not all(str(f.get("Code", "")) in _BATCH_FAIL_RETRY_CODES for f in failed):
            msg = f"send_message_batch non-retryable failure: {failed}"
            raise RuntimeError(msg) from None

        failed_ids = {str(f["Id"]) for f in failed}
        pending = [e for e in pending if e["Id"] in failed_ids]
        if not pending:
            return

        metrics.send_batch_throttle_retries += 1
        if attempt + 1 >= max_attempts:
            msg = f"send_message_batch still failing after retries: {failed}"
            raise RuntimeError(msg)
        delay_ms = compute_backoff_delay_ms(attempt, rng=rng)
        await sleeper(delay_ms / 1000.0)


def _batch_entries_from_units(units: list[SendUnitV1]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for u in units:
        eid = uuid.uuid4().hex[:20]
        body = json.dumps(
            u.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        entries.append({"Id": eid, "MessageBody": body})
    return entries
