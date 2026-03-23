"""Orchestration for message submission — persistence only via PersistenceHttpClient."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import httpx

from inspectio_exercise.api import config
from inspectio_exercise.domain.sharding import pending_prefix_for_shard, shard_id_for_message
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.persistence.object_write import ObjectWrite

logger = logging.getLogger(__name__)

PersistPendingBatchFn = Callable[[Sequence[ObjectWrite]], Awaitable[None]]


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class SubmittedMessage:
    message_id: str
    pending_key: str
    shard_id: int


def worker_activation_base_urls() -> list[str]:
    return [u.strip() for u in config.INSPECTIO_WORKER_ACTIVATION_URLS.split(",") if u.strip()]


def _pending_submission_record(
    *,
    body: str,
    should_fail: bool,
    to: str,
    total_shards: int,
) -> tuple[SubmittedMessage, ObjectWrite]:
    """Build pending key + JSON bytes + routing metadata (no I/O)."""
    message_id = str(uuid.uuid4())
    shard_id = shard_id_for_message(message_id, total_shards)
    key = f"{pending_prefix_for_shard(shard_id)}{message_id}.json"
    now_ms = _now_ms()
    payload: dict[str, str | bool] = {"to": to, "body": body}
    if should_fail:
        payload["shouldFail"] = True
    record = {
        "messageId": message_id,
        "attemptCount": 0,
        "nextDueAt": now_ms,
        "status": "pending",
        "payload": payload,
        "history": [],
    }
    raw = json.dumps(record, separators=(",", ":")).encode("utf-8")
    submitted = SubmittedMessage(message_id=message_id, pending_key=key, shard_id=shard_id)
    return submitted, ObjectWrite(key=key, body=raw, content_type="application/json")


async def submit_message(
    persistence: PersistenceHttpClient,
    *,
    body: str,
    should_fail: bool = False,
    to: str,
    total_shards: int,
    persist_pending_batch: PersistPendingBatchFn | None = None,
) -> SubmittedMessage:
    """Persist a new pending record; return ids for activation routing."""
    submitted, ow = _pending_submission_record(
        body=body,
        should_fail=should_fail,
        to=to,
        total_shards=total_shards,
    )
    writer = persist_pending_batch if persist_pending_batch is not None else persistence.put_objects
    await writer((ow,))
    return submitted


async def request_immediate_activation(
    worker_clients: Sequence[httpx.AsyncClient],
    *,
    submitted: SubmittedMessage,
    shards_per_pod: int,
) -> None:
    """Best-effort: run worker attempt #1 immediately (assignment ``newMessage`` semantics)."""
    if not worker_clients:
        return
    idx = submitted.shard_id // shards_per_pod % len(worker_clients)
    client = worker_clients[idx]
    try:
        response = await client.post(
            config.WORKER_ACTIVATE_PENDING_HTTP_PATH,
            json={"pendingKey": submitted.pending_key},
            timeout=config.PEER_HTTP_CLIENT_TIMEOUT_SEC,
        )
        if response.status_code == 204:
            return
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning(
            "worker activation failed for message_id=%s pending_key=%s (will retry on tick)",
            submitted.message_id,
            submitted.pending_key,
            exc_info=True,
        )


async def submit_messages_repeat_parallel(
    persistence: PersistenceHttpClient,
    *,
    body: str,
    count: int,
    should_fail: bool,
    to: str,
    total_shards: int,
    worker_clients: Sequence[httpx.AsyncClient],
    shards_per_pod: int,
    concurrency: int,
    persist_pending_batch: PersistPendingBatchFn | None = None,
) -> list[str]:
    """Create ``count`` messages with bounded parallel persistence + activation."""
    rows = [
        _pending_submission_record(
            body=body,
            should_fail=should_fail,
            to=to,
            total_shards=total_shards,
        )
        for _ in range(count)
    ]
    writer = persist_pending_batch if persist_pending_batch is not None else persistence.put_objects
    batch = max(1, config.REPEAT_SUBMIT_PUT_BATCH_SIZE)
    for offset in range(0, len(rows), batch):
        chunk = rows[offset : offset + batch]
        await writer([ow for _, ow in chunk])

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _activate(submitted: SubmittedMessage) -> str:
        async with sem:
            await request_immediate_activation(
                worker_clients,
                submitted=submitted,
                shards_per_pod=shards_per_pod,
            )
            return submitted.message_id

    return list(await asyncio.gather(*(_activate(s) for s, _ in rows)))
