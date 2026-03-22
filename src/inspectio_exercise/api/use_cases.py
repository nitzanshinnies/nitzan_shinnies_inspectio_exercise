"""Orchestration for message submission — persistence only via PersistenceHttpClient."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import httpx

from inspectio_exercise.api import config
from inspectio_exercise.domain.sharding import pending_prefix_for_shard, shard_id_for_message
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class SubmittedMessage:
    message_id: str
    pending_key: str
    shard_id: int


def worker_activation_base_urls() -> list[str]:
    return [u.strip() for u in config.INSPECTIO_WORKER_ACTIVATION_URLS.split(",") if u.strip()]


async def submit_message(
    persistence: PersistenceHttpClient,
    *,
    body: str,
    should_fail: bool = False,
    to: str,
    total_shards: int,
) -> SubmittedMessage:
    """Persist a new pending record; return ids for activation routing."""
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
    await persistence.put_object(key, raw)
    return SubmittedMessage(message_id=message_id, pending_key=key, shard_id=shard_id)


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
) -> list[str]:
    """Create ``count`` messages with bounded parallel persistence + activation."""
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one() -> str:
        async with sem:
            submitted = await submit_message(
                persistence,
                body=body,
                should_fail=should_fail,
                to=to,
                total_shards=total_shards,
            )
            await request_immediate_activation(
                worker_clients,
                submitted=submitted,
                shards_per_pod=shards_per_pod,
            )
            return submitted.message_id

    return list(await asyncio.gather(*(_one() for _ in range(count))))
