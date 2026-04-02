"""Worker entry: SQS ingest + scheduler + optional snapshot ."""

from __future__ import annotations

import asyncio
import logging

import aioboto3
import httpx
import redis.asyncio as redis

from inspectio.domain.sharding import owned_shard_range
from inspectio.ingest.sqs_fifo_consumer import RawSqsMessage, SqsFifoBatchFetcher
from inspectio.journal.replay import load_snapshot_if_present
from inspectio.journal.writer import (
    JournalWriter,
    bootstrap_hwm_for_shards,
    write_snapshot,
)
from inspectio import scheduler_surface
from inspectio.settings import Settings
from inspectio.worker.handlers import process_raw_sqs_message
from inspectio.worker.runtime import WorkerRuntime

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("inspectio.worker")
logging.getLogger("aiobotocore.credentials").setLevel(logging.WARNING)
logging.getLogger("botocore.credentials").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


async def _snapshot_loop(
    runtime: WorkerRuntime,
    journal: JournalWriter,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        await asyncio.sleep(settings.snapshot_interval_sec)
        start, end = runtime.owned_range
        for sid in range(start, end):
            pending = [
                p for p in runtime.pending_snapshot_rows() if p["shardId"] == sid
            ]
            await write_snapshot(
                settings,
                sid,
                journal.get_last_record_index(sid),
                pending,
            )


async def _journal_flush_loop(
    journal: JournalWriter,
    stop: asyncio.Event,
) -> None:
    await journal.periodic_flush_loop(stop)


async def _wakeup_loop(stop: asyncio.Event, interval_ms: int) -> None:
    while not stop.is_set():
        await asyncio.sleep(interval_ms / 1000.0)
        scheduler_surface.wakeup()


async def _sqs_loop(
    settings: Settings,
    journal: JournalWriter,
    redis_client: redis.Redis,
    stop: asyncio.Event,
) -> None:
    fetcher = SqsFifoBatchFetcher(settings)
    await fetcher.start()
    try:
        while not stop.is_set():
            try:
                batch = await fetcher.receive_messages(max_messages=10, wait_seconds=20)
            except Exception as exc:
                log.exception("sqs receive failed: %s", exc)
                await asyncio.sleep(1.0)
                continue
            if not batch:
                continue

            async def _one(raw: RawSqsMessage) -> tuple[bool, int | None]:
                try:
                    return await process_raw_sqs_message(
                        raw,
                        settings=settings,
                        writer=journal,
                        redis_client=redis_client,
                    )
                except Exception:
                    log.exception("ingest handler failed")
                    return False, None

            outcomes = await asyncio.gather(*(_one(r) for r in batch))
            to_delete: list[str] = []
            shards_to_flush: set[int] = set()
            for raw, outcome in zip(batch, outcomes, strict=True):
                should_delete, shard_flush = outcome
                if should_delete:
                    to_delete.append(raw.receipt_handle)
                    if shard_flush is not None:
                        shards_to_flush.add(shard_flush)
            for sid in shards_to_flush:
                await journal.flush_shard(sid)
            for i in range(0, len(to_delete), 10):
                await fetcher.delete_messages_batch(to_delete[i : i + 10])
    finally:
        await fetcher.stop()


async def _run() -> None:
    settings = Settings()
    stop = asyncio.Event()
    redis_client = redis.from_url(settings.redis_url, decode_responses=False)
    http_client = httpx.AsyncClient(timeout=60.0)
    start, end = owned_shard_range(
        settings.worker_index,
        settings.total_shards,
        settings.worker_replicas,
    )
    shard_ids = list(range(start, end))
    hwm = await bootstrap_hwm_for_shards(settings, shard_ids)
    journal = JournalWriter(settings, initial_hwm=hwm)
    await journal.start()
    runtime = WorkerRuntime(settings, journal, http_client)
    scheduler_surface.configure_runtime(runtime)

    if settings.s3_bucket.strip():
        session = aioboto3.Session()
        kwargs: dict = {"region_name": settings.aws_region}
        if settings.aws_endpoint_url:
            kwargs["endpoint_url"] = settings.aws_endpoint_url
        async with session.client("s3", **kwargs) as s3:
            for sid in shard_ids:
                snap = await load_snapshot_if_present(s3, settings.s3_bucket, sid)
                if snap is not None:
                    runtime.restore_snapshot_pending(snap.pending)

    sqs_tasks = [
        asyncio.create_task(_sqs_loop(settings, journal, redis_client, stop))
        for _ in range(settings.sqs_receive_concurrency)
    ]
    tasks = [
        *sqs_tasks,
        asyncio.create_task(
            _wakeup_loop(stop, settings.wakeup_interval_ms),
        ),
        asyncio.create_task(runtime.terminal_retry_loop(stop)),
        asyncio.create_task(_journal_flush_loop(journal, stop)),
        asyncio.create_task(_snapshot_loop(runtime, journal, settings, stop)),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        await journal.flush_all()
        await journal.stop()
        await http_client.aclose()
        await redis_client.aclose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
