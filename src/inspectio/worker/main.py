"""Process entry for `inspectio-worker` (P5 ingest + journal + checkpoint loop)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

import aioboto3
import httpx
import redis.asyncio as redis

from inspectio.ingest.ingest_consumer import IngestConsumer
from inspectio.ingest.sqs_fifo_consumer import SqsFifoBatchFetcher
from inspectio.domain.sharding import (
    owned_shard_range,
    validate_total_shards_vs_workers,
)
from inspectio.journal.records import JournalRecordV1
from inspectio.journal.replay import ReplayS3Store, apply_tail_records
from inspectio.journal.writer import JournalWriter
from inspectio.perf_log import perf_line
from inspectio.settings import get_settings
from inspectio.sms.client import SmsClient
from inspectio.worker.handlers import IngestJournalHandler, RedisIdempotencyStore
from inspectio.worker.runtime import InMemorySchedulerRuntime

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("inspectio.worker")

DEFAULT_POLL_INTERVAL_SEC = 1.0


class ShardedJournalFacade:
    """Routes journal operations to per-shard JournalWriter instances."""

    def __init__(
        self,
        *,
        writer_factory: Callable[[int], JournalWriter],
        managed_shards: set[int] | None = None,
    ) -> None:
        self._writer_factory = writer_factory
        self._writers: dict[int, JournalWriter] = {}
        self._managed_shards = managed_shards if managed_shards is not None else set()
        self._dirty_shards: set[int] = set()

    async def append(self, record) -> None:
        writer = self._get_writer(record.shard_id)
        await writer.append(record)
        self._dirty_shards.add(record.shard_id)
        self._managed_shards.add(record.shard_id)

    async def flush(self) -> None:
        for shard_id in sorted(self._dirty_shards):
            await self._get_writer(shard_id).flush(force=True)
        self._dirty_shards.clear()

    async def write_snapshot_if_due(
        self,
        *,
        shard_id: int,
        last_record_index: int,
        active: dict,
        now_ms: int,
    ) -> None:
        self._managed_shards.add(shard_id)
        await self._get_writer(shard_id).write_snapshot_if_due(
            shard_id=shard_id,
            last_record_index=last_record_index,
            active=active,
            now_ms=now_ms,
        )

    @property
    def managed_shards(self) -> set[int]:
        return set(self._managed_shards)

    def _get_writer(self, shard_id: int) -> JournalWriter:
        existing = self._writers.get(shard_id)
        if existing is not None:
            return existing
        writer = self._writer_factory(shard_id)
        self._writers[shard_id] = writer
        return writer


class NotificationTerminalClient:
    """HTTP client for writing terminal outcomes to notification service."""

    def __init__(self, *, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def post_terminal(self, payload: dict[str, object]) -> None:
        url = f"{self._base_url}/internal/v1/outcomes/terminal"
        t0 = time.monotonic_ns()
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        perf_line(
            "notification_terminal_http",
            message_id=payload.get("messageId", ""),
            http_status=response.status_code,
            http_ms=f"{(time.monotonic_ns() - t0) / 1_000_000:.3f}",
        )


class TerminalOutcomePublisher(Protocol):
    async def post_terminal(self, payload: dict[str, object]) -> None: ...


async def run_consumer_loop(
    *,
    consume_once: Callable[[], Awaitable[int]],
    wakeup_once: Callable[[], Awaitable[int]],
    snapshot_once: Callable[[], Awaitable[int]] | None = None,
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
    sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Continuously poll ingest stream and run wakeup on a target cadence."""
    while True:
        started = time.monotonic()
        iter_start_ns = time.monotonic_ns()
        processed = await consume_once()
        c1 = time.monotonic_ns()
        processed += await wakeup_once()
        w1 = time.monotonic_ns()
        snap_ms = 0.0
        if snapshot_once is not None:
            s0 = time.monotonic_ns()
            processed += await snapshot_once()
            snap_ms = (time.monotonic_ns() - s0) / 1_000_000
        elapsed = time.monotonic() - started
        perf_line(
            "worker_loop_iteration",
            consume_once_ms=f"{(c1 - iter_start_ns) / 1_000_000:.3f}",
            wakeup_once_ms=f"{(w1 - c1) / 1_000_000:.3f}",
            snapshot_once_ms=f"{snap_ms:.3f}",
            iteration_total_ms=f"{(time.monotonic_ns() - iter_start_ns) / 1_000_000:.3f}",
            processed=processed,
        )
        remaining = poll_interval_sec - elapsed
        if remaining > 0:
            await sleep_func(remaining)


def main() -> None:
    """Run single-worker ingest consumer loop for P5 path."""
    asyncio.run(_run())


async def _run() -> None:
    settings = get_settings()
    validate_total_shards_vs_workers(
        settings.inspectio_total_shards,
        settings.inspectio_worker_replicas,
    )
    if not settings.inspectio_s3_bucket:
        msg = "INSPECTIO_S3_BUCKET must be configured for P5 worker"
        raise ValueError(msg)
    if not settings.inspectio_ingest_queue_url.strip():
        msg = "INSPECTIO_INGEST_QUEUE_URL must be configured for P5 worker"
        raise ValueError(msg)
    owned_shards = _owned_shard_ids(
        worker_index=settings.inspectio_worker_index,
        total_shards=settings.inspectio_total_shards,
        worker_replicas=settings.inspectio_worker_replicas,
    )

    session = aioboto3.Session()
    redis_client = redis.from_url(settings.inspectio_redis_url, decode_responses=True)
    try:
        async with session.client(
            "s3", region_name=settings.inspectio_aws_region
        ) as s3_client:
            async with session.client(
                "sqs",
                region_name=settings.inspectio_aws_region,
            ) as sqs_client:
                managed_shards = set(owned_shards)

                def _writer_factory(_shard_id: int) -> JournalWriter:
                    return JournalWriter(
                        s3_client=s3_client,
                        bucket=settings.inspectio_s3_bucket,
                        flush_interval_ms=settings.inspectio_journal_flush_interval_ms,
                        flush_max_lines=settings.inspectio_journal_flush_max_lines,
                        snapshot_interval_sec=settings.inspectio_snapshot_interval_sec,
                    )

                journal_writer = ShardedJournalFacade(
                    writer_factory=_writer_factory,
                    managed_shards=managed_shards,
                )
                runtime = InMemorySchedulerRuntime(
                    now_ms=lambda: int(time.time() * 1000),
                    sms_sender=SmsClient(
                        base_url=settings.inspectio_sms_url,
                        timeout_sec=settings.inspectio_sms_http_timeout_sec,
                    ),
                )
                handler = IngestJournalHandler(
                    idempotency_store=RedisIdempotencyStore(redis_client=redis_client),
                    idempotency_ttl_sec=settings.inspectio_idempotency_ttl_sec,
                    runtime=runtime,
                )

                async def _delete_sqs(receipt_handle: str) -> None:
                    await sqs_client.delete_message(
                        QueueUrl=settings.inspectio_ingest_queue_url,
                        ReceiptHandle=receipt_handle,
                    )

                consumer = IngestConsumer(
                    handler=handler,
                    journal_writer=journal_writer,
                    checkpoint_store=None,
                    sqs_delete=_delete_sqs,
                )
                fetcher = SqsFifoBatchFetcher(
                    sqs_client=sqs_client,
                    queue_url=settings.inspectio_ingest_queue_url,
                    worker_index=settings.inspectio_worker_index,
                    worker_replicas=settings.inspectio_worker_replicas,
                    total_shards=settings.inspectio_total_shards,
                )
                replay_store = ReplayS3Store(
                    s3_client=s3_client,
                    bucket=settings.inspectio_s3_bucket,
                )
                await _restore_runtime_from_s3_snapshots(
                    runtime=runtime,
                    replay_store=replay_store,
                    shard_ids=owned_shards,
                )
                runtime_cursor = runtime.journal_length()
                notification_client = NotificationTerminalClient(
                    base_url=settings.inspectio_notification_base_url
                )

                async def _consume_once() -> int:
                    nonlocal runtime_cursor
                    processed = await consumer.consume_once(
                        fetch_records=fetcher.fetch_records
                    )
                    new_runtime_lines = runtime.journal_since(runtime_cursor)
                    if new_runtime_lines:
                        p0 = time.monotonic_ns()
                        await _publish_terminal_outcomes(
                            lines=new_runtime_lines,
                            notification_client=notification_client,
                        )
                        perf_line(
                            "worker_ingest_publish",
                            terminal_lines=len(new_runtime_lines),
                            publish_ms=f"{(time.monotonic_ns() - p0) / 1_000_000:.3f}",
                        )
                    # Ingest path journal lines are already persisted by consumer; keep cursor aligned.
                    runtime_cursor = runtime.journal_length()
                    return processed

                async def _wakeup_once() -> int:
                    nonlocal runtime_cursor
                    w0 = time.monotonic_ns()
                    await runtime.wakeup()
                    w1 = time.monotonic_ns()
                    new_lines = runtime.journal_since(runtime_cursor)
                    if not new_lines:
                        perf_line(
                            "worker_wakeup",
                            scheduler_wakeup_ms=f"{(w1 - w0) / 1_000_000:.3f}",
                            new_lines=0,
                        )
                        return 0
                    a0 = time.monotonic_ns()
                    for line in new_lines:
                        await journal_writer.append(line)
                    a1 = time.monotonic_ns()
                    await journal_writer.flush()
                    f1 = time.monotonic_ns()
                    p0 = time.monotonic_ns()
                    await _publish_terminal_outcomes(
                        lines=new_lines,
                        notification_client=notification_client,
                    )
                    p1 = time.monotonic_ns()
                    perf_line(
                        "worker_wakeup",
                        scheduler_wakeup_ms=f"{(w1 - w0) / 1_000_000:.3f}",
                        new_lines=len(new_lines),
                        journal_append_ms=f"{(a1 - a0) / 1_000_000:.3f}",
                        journal_flush_ms=f"{(f1 - a1) / 1_000_000:.3f}",
                        notification_publish_ms=f"{(p1 - p0) / 1_000_000:.3f}",
                    )
                    runtime_cursor = runtime.journal_length()
                    return len(new_lines)

                async def _snapshot_once() -> int:
                    wrote = 0
                    now_ms = int(time.time() * 1000)
                    s0 = time.monotonic_ns()
                    by_shard = runtime.active_snapshot_view_by_shard()
                    for shard_id in sorted(journal_writer.managed_shards):
                        active = by_shard.get(shard_id, {})
                        last_record_index = runtime.last_record_index_for_shard(
                            shard_id
                        )
                        await journal_writer.write_snapshot_if_due(
                            shard_id=shard_id,
                            last_record_index=last_record_index,
                            active=active,
                            now_ms=now_ms,
                        )
                        wrote += 1
                    perf_line(
                        "worker_snapshot_once",
                        managed_shards=wrote,
                        total_ms=f"{(time.monotonic_ns() - s0) / 1_000_000:.3f}",
                    )
                    return wrote

                await run_consumer_loop(
                    consume_once=_consume_once,
                    wakeup_once=_wakeup_once,
                    snapshot_once=_snapshot_once,
                    poll_interval_sec=settings.inspectio_wakeup_interval_ms / 1000.0,
                )
    finally:
        await redis_client.aclose()


async def _restore_runtime_from_s3_snapshots(
    *,
    runtime: InMemorySchedulerRuntime,
    replay_store: ReplayS3Store,
    shard_ids: list[int],
) -> None:
    for shard_id in shard_ids:
        snapshot = await replay_store.load_latest(shard_id=shard_id)
        if snapshot is None:
            continue
        tail = await replay_store.load_tail_segments(shard_id=shard_id)
        replayed = apply_tail_records(snapshot=snapshot, gzip_segments=tail)
        runtime.restore_pending_for_shard(shard_id=shard_id, active=replayed.active)


def _owned_shard_ids(
    *,
    worker_index: int,
    total_shards: int,
    worker_replicas: int,
) -> list[int]:
    start, end_excl = owned_shard_range(worker_index, total_shards, worker_replicas)
    return list(range(start, end_excl))


def _terminal_payload_from_record(
    record: JournalRecordV1,
) -> dict[str, object] | None:
    if record.type != "TERMINAL":
        return None
    payload = {
        "messageId": record.message_id,
        "terminalStatus": record.payload["status"],
        "attemptCount": record.payload["attemptCount"],
        "finalTimestampMs": record.ts_ms,
        "reason": record.payload.get("reason"),
    }
    return payload


async def _publish_terminal_outcomes(
    *,
    lines: list[JournalRecordV1],
    notification_client: TerminalOutcomePublisher,
) -> None:
    for line in lines:
        payload = _terminal_payload_from_record(line)
        if payload is None:
            continue
        await notification_client.post_terminal(payload)


if __name__ == "__main__":
    main()
