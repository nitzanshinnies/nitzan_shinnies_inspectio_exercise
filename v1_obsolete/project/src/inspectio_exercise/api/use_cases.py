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
from inspectio_exercise.common.performance_logging import duration_ms_since, log_performance
from inspectio_exercise.domain.sharding import pending_prefix_for_shard, shard_id_for_message
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.persistence.object_write import ObjectWrite

logger = logging.getLogger(__name__)

PersistPendingBatchFn = Callable[[Sequence[ObjectWrite]], Awaitable[None]]
OPERATION_API_ENQUEUE_BATCH: str = "api_enqueue_batch"
OPERATION_API_REPEAT_ENQUEUE: str = "api_repeat_enqueue"
OPERATION_API_ACTIVATION_BATCH: str = "api_activation_batch"


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
    """Best-effort: worker enqueues pending row and wakes scheduler (attempt #1 on next tick)."""
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


async def request_immediate_activation_batch(
    worker_clients: Sequence[httpx.AsyncClient],
    *,
    submitted: Sequence[SubmittedMessage],
    shards_per_pod: int,
) -> None:
    """Best-effort: one or more batch HTTP calls per worker (``activate-pending-batch``)."""
    if not worker_clients or not submitted:
        return
    activation_start = time.perf_counter()
    attempts = 0
    failures = 0
    batch_max = config.WORKER_ACTIVATION_BATCH_MAX_KEYS
    idx_to_keys: dict[int, list[str]] = {}
    for s in submitted:
        idx = s.shard_id // shards_per_pod % len(worker_clients)
        idx_to_keys.setdefault(idx, []).append(s.pending_key)
    for idx, keys in idx_to_keys.items():
        if not keys:
            continue
        client = worker_clients[idx]
        offset = 0
        while offset < len(keys):
            chunk = keys[offset : offset + batch_max]
            offset += len(chunk)
            attempts += 1
            try:
                response = await client.post(
                    config.WORKER_ACTIVATE_PENDING_BATCH_HTTP_PATH,
                    json={"pendingKeys": chunk},
                    timeout=config.PEER_HTTP_CLIENT_TIMEOUT_SEC,
                )
                response.raise_for_status()
            except httpx.HTTPError:
                failures += 1
                logger.warning(
                    "worker batch activation failed worker_index=%s chunk_len=%s",
                    idx,
                    len(chunk),
                    exc_info=True,
                )
    log_performance(
        component="api",
        operation=OPERATION_API_ACTIVATION_BATCH,
        activation_attempts=attempts,
        activation_failures=failures,
        activation_target_workers=len(idx_to_keys),
        submitted_count=len(submitted),
        duration_ms=duration_ms_since(activation_start),
    )


def schedule_background_worker_activation(awaitable: Awaitable[None]) -> None:
    """Run activation without blocking the HTTP response (best-effort; errors logged)."""

    async def _run() -> None:
        try:
            await awaitable
        except Exception:
            logger.exception("background worker activation failed")

    asyncio.create_task(_run())


async def _persist_repeat_rows(
    rows: Sequence[tuple[SubmittedMessage, ObjectWrite]],
    *,
    writer: PersistPendingBatchFn,
) -> None:
    batch_size = max(1, config.REPEAT_SUBMIT_PUT_BATCH_SIZE)
    max_concurrency = max(1, config.REPEAT_SUBMIT_PUT_MAX_CONCURRENCY)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _put_chunk(chunk: Sequence[ObjectWrite]) -> None:
        async with semaphore:
            chunk_start = time.perf_counter()
            await writer(chunk)
            log_performance(
                component="api",
                operation=OPERATION_API_ENQUEUE_BATCH,
                enqueue_batch_size=len(chunk),
                duration_ms=duration_ms_since(chunk_start),
            )

    tasks: list[asyncio.Task[None]] = []
    for offset in range(0, len(rows), batch_size):
        chunk = rows[offset : offset + batch_size]
        object_writes = [ow for _, ow in chunk]
        tasks.append(asyncio.create_task(_put_chunk(object_writes)))
    await asyncio.gather(*tasks)


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
    persist_pending_batch: PersistPendingBatchFn | None = None,
) -> list[str]:
    """Create ``count`` messages; chunked persistence + background batch activation."""
    repeat_start = time.perf_counter()
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
    await _persist_repeat_rows(rows, writer=writer)

    submitted_list = [s for s, _ in rows]
    log_performance(
        component="api",
        operation=OPERATION_API_REPEAT_ENQUEUE,
        accepted=count,
        enqueue_batches=(count + max(1, config.REPEAT_SUBMIT_PUT_BATCH_SIZE) - 1)
        // max(1, config.REPEAT_SUBMIT_PUT_BATCH_SIZE),
        enqueue_concurrency=max(1, config.REPEAT_SUBMIT_PUT_MAX_CONCURRENCY),
        duration_ms=duration_ms_since(repeat_start),
    )
    schedule_background_worker_activation(
        request_immediate_activation_batch(
            worker_clients,
            submitted=submitted_list,
            shards_per_pod=shards_per_pod,
        )
    )
    return [s.message_id for s, _ in rows]
