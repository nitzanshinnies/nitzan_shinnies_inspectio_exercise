"""Process entry for `inspectio-worker` (P5 ingest + journal + checkpoint loop)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import aioboto3
import redis.asyncio as redis

from inspectio.ingest.kinesis_consumer import (
    KinesisBatchFetcher,
    KinesisIngestConsumer,
    S3CheckpointStore,
)
from inspectio.domain.sharding import (
    owned_shard_range,
    validate_total_shards_vs_workers,
)
from inspectio.journal.replay import ReplayS3Store, apply_tail_records
from inspectio.journal.writer import JournalWriter
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
        processed = await consume_once()
        processed += await wakeup_once()
        if snapshot_once is not None:
            processed += await snapshot_once()
        elapsed = time.monotonic() - started
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
                "kinesis",
                region_name=settings.inspectio_aws_region,
            ) as kinesis_client:
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
                checkpoint_store = S3CheckpointStore(
                    s3_client=s3_client,
                    bucket=settings.inspectio_s3_bucket,
                    stream_name=settings.inspectio_kinesis_stream_name,
                    key_prefix=settings.inspectio_kinesis_checkpoint_key_prefix,
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
                consumer = KinesisIngestConsumer(
                    handler=handler,
                    journal_writer=journal_writer,
                    checkpoint_store=checkpoint_store,
                )
                fetcher = KinesisBatchFetcher(
                    kinesis_client=kinesis_client,
                    stream_name=settings.inspectio_kinesis_stream_name,
                    worker_index=settings.inspectio_worker_index,
                    worker_replicas=settings.inspectio_worker_replicas,
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

                async def _consume_once() -> int:
                    nonlocal runtime_cursor
                    processed = await consumer.consume_once(
                        fetch_records=fetcher.fetch_records
                    )
                    # Ingest path journal lines are already persisted by consumer; keep cursor aligned.
                    runtime_cursor = runtime.journal_length()
                    return processed

                async def _wakeup_once() -> int:
                    nonlocal runtime_cursor
                    await runtime.wakeup()
                    new_lines = runtime.journal_since(runtime_cursor)
                    if not new_lines:
                        return 0
                    for line in new_lines:
                        await journal_writer.append(line)
                    await journal_writer.flush()
                    runtime_cursor = runtime.journal_length()
                    return len(new_lines)

                async def _snapshot_once() -> int:
                    wrote = 0
                    now_ms = int(time.time() * 1000)
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
                    return wrote

                await run_consumer_loop(
                    consume_once=_consume_once,
                    wakeup_once=_wakeup_once,
                    snapshot_once=_snapshot_once,
                    poll_interval_sec=settings.inspectio_wakeup_interval_ms / 1000.0,
                )
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    main()


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
