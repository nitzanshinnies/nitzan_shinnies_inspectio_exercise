"""Persistence writer process entrypoint (P12.3)."""

from __future__ import annotations

import asyncio
import logging
import time

import aioboto3

from inspectio.v3.persistence_transport.sqs_consumer import (
    SqsPersistenceTransportConsumer,
)
from inspectio.v3.persistence_writer.s3_store import S3PersistenceObjectStore
from inspectio.v3.persistence_writer.writer import BufferedPersistenceWriter
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

    async with (
        session.client("sqs", **client_kw) as sqs_client,
        session.client(
            "s3",
            **client_kw,
        ) as s3_client,
    ):
        consumer = SqsPersistenceTransportConsumer(
            client=sqs_client,
            queue_url=settings.persist_transport_queue_url,
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
            "persistence writer started queue=%s", settings.persist_transport_queue_url
        )
        while True:
            events = await consumer.receive_many(
                max_events=settings.writer_receive_max_events
            )
            if events:
                await writer.ingest_events(events)
            flushed = await writer.flush_due(force=False)
            if flushed:
                await consumer.ack_many(flushed)
            if not events:
                await asyncio.sleep(settings.writer_idle_sleep_sec)


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
