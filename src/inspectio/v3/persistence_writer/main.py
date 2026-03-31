"""Persistence writer process entrypoint (P12.3)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict

import aioboto3

from inspectio.v3.persistence_transport.sqs_consumer import (
    SqsPersistenceTransportConsumer,
)
from inspectio.v3.persistence_writer.s3_store import S3PersistenceObjectStore
from inspectio.v3.persistence_writer.writer import BufferedPersistenceWriter
from inspectio.v3.schemas.persistence_event import PersistenceEventV1
from inspectio.v3.settings import V3PersistenceWriterSettings

_log = logging.getLogger(__name__)


async def amain() -> None:
    settings = V3PersistenceWriterSettings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    session = aioboto3.Session()
    client_kw: dict[str, str] = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        client_kw["endpoint_url"] = settings.aws_endpoint_url
    if settings.aws_access_key_id:
        client_kw["aws_access_key_id"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        client_kw["aws_secret_access_key"] = settings.aws_secret_access_key

    queue_url = settings.resolved_transport_queue_url()
    async with (
        session.client("sqs", **client_kw) as sqs_client,
        session.client(
            "s3",
            **client_kw,
        ) as s3_client,
    ):
        consumer = SqsPersistenceTransportConsumer(
            client=sqs_client,
            queue_url=queue_url,
            wait_seconds=settings.writer_receive_wait_seconds,
            receive_max_events=settings.writer_receive_max_events,
        )
        store = S3PersistenceObjectStore(
            client=s3_client,
            bucket=settings.persistence_s3_bucket,
            prefix=settings.persistence_s3_prefix,
        )

        def clock_ms() -> int:
            return int(time.time() * 1000)

        writer = BufferedPersistenceWriter(
            store=store,
            clock_ms=clock_ms,
            flush_max_events=settings.writer_flush_max_events,
            flush_interval_ms=settings.writer_flush_interval_ms,
            dedupe_event_id_cap=settings.writer_dedupe_event_id_cap,
            write_max_attempts=settings.writer_write_max_attempts,
            backoff_base_ms=settings.writer_write_backoff_base_ms,
            backoff_max_ms=settings.writer_write_backoff_max_ms,
            backoff_jitter_fraction=settings.writer_write_backoff_jitter,
        )

        _log.info(
            "persistence writer started queue=%s shard=%s",
            queue_url,
            settings.writer_shard_id,
        )
        last_snapshot_ms = clock_ms()

        async def ack_many_with_retry(events_to_ack: list[PersistenceEventV1]) -> int:
            ack_by_shard: dict[int, int] = defaultdict(int)
            for event in events_to_ack:
                ack_by_shard[event.shard] += 1
            for attempt in range(settings.writer_write_max_attempts):
                try:
                    ack_started = time.perf_counter()
                    await consumer.ack_many(events_to_ack)
                    return int((time.perf_counter() - ack_started) * 1000)
                except Exception:  # noqa: BLE001
                    retry_now = clock_ms()
                    for shard in ack_by_shard:
                        writer.metrics.observe_retry(
                            shard=shard,
                            operation="ack",
                            now_ms=retry_now,
                        )
                    if attempt + 1 >= settings.writer_write_max_attempts:
                        raise
                    backoff_ms = min(
                        settings.writer_write_backoff_max_ms,
                        settings.writer_write_backoff_base_ms * (2**attempt),
                    )
                    await asyncio.sleep(backoff_ms / 1000.0)
            return 0

        while True:
            events = await consumer.receive_many(
                max_events=settings.writer_receive_max_events
            )
            now_ms = clock_ms()
            writer.metrics.observe_poll(idle=not events)
            if events:
                events_by_shard: dict[int, int] = defaultdict(int)
                oldest_emitted_at_by_shard: dict[int, int] = {}
                for event in events:
                    events_by_shard[event.shard] += 1
                    oldest = oldest_emitted_at_by_shard.get(event.shard)
                    if oldest is None or event.emitted_at_ms < oldest:
                        oldest_emitted_at_by_shard[event.shard] = event.emitted_at_ms
                for shard, count in events_by_shard.items():
                    writer.metrics.observe_receive_batch(
                        shard=shard,
                        events=count,
                        now_ms=now_ms,
                    )
                    oldest_emitted_at = oldest_emitted_at_by_shard[shard]
                    writer.metrics.observe_transport_oldest_age(
                        shard=shard,
                        age_ms=max(0, now_ms - oldest_emitted_at),
                        now_ms=now_ms,
                    )
                await writer.ingest_events(events)
            flushed = await writer.flush_due(force=False)
            if flushed:
                ack_latency_ms = await ack_many_with_retry(flushed)
                ack_by_shard: dict[int, int] = defaultdict(int)
                for event in flushed:
                    ack_by_shard[event.shard] += 1
                ack_now = clock_ms()
                for shard, count in ack_by_shard.items():
                    writer.metrics.observe_ack_batch(
                        shard=shard,
                        events=count,
                        latency_ms=ack_latency_ms,
                        now_ms=ack_now,
                    )
            snapshot_now = clock_ms()
            if (
                snapshot_now - last_snapshot_ms
                >= settings.writer_observability_snapshot_interval_sec * 1000
            ):
                _log.info(
                    "writer_snapshot %s",
                    json.dumps(
                        writer.metrics.snapshot(now_ms=snapshot_now),
                        sort_keys=True,
                    ),
                )
                last_snapshot_ms = snapshot_now
            if not events:
                await asyncio.sleep(settings.writer_idle_sleep_sec)


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
