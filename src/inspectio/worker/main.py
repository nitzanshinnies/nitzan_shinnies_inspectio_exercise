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
from inspectio.journal.writer import JournalWriter
from inspectio.settings import get_settings
from inspectio.sms.client import SmsClient
from inspectio.worker.handlers import IngestJournalHandler, RedisIdempotencyStore
from inspectio.worker.runtime import InMemorySchedulerRuntime

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("inspectio.worker")

DEFAULT_POLL_INTERVAL_SEC = 1.0


async def run_consumer_loop(
    *,
    consume_once: Callable[[], Awaitable[int]],
    wakeup_once: Callable[[], Awaitable[int]],
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC,
) -> None:
    """Continuously poll ingest stream and process available records."""
    while True:
        processed = await consume_once()
        processed += await wakeup_once()
        if processed == 0:
            await asyncio.sleep(poll_interval_sec)


def main() -> None:
    """Run single-worker ingest consumer loop for P5 path."""
    asyncio.run(_run())


async def _run() -> None:
    settings = get_settings()
    if settings.inspectio_worker_replicas != 1:
        msg = "P5 supports INSPECTIO_WORKER_REPLICAS=1 only (§29.6)"
        raise ValueError(msg)
    if not settings.inspectio_s3_bucket:
        msg = "INSPECTIO_S3_BUCKET must be configured for P5 worker"
        raise ValueError(msg)

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
                journal_writer = JournalWriter(
                    s3_client=s3_client,
                    bucket=settings.inspectio_s3_bucket,
                    flush_interval_ms=settings.inspectio_journal_flush_interval_ms,
                    flush_max_lines=settings.inspectio_journal_flush_max_lines,
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

                await run_consumer_loop(
                    consume_once=_consume_once,
                    wakeup_once=_wakeup_once,
                )
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    main()
