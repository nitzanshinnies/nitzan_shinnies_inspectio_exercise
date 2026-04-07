"""Kubernetes StatefulSet worker: recovery, WAL flush, 500 ms scheduler loop."""

from __future__ import annotations

import asyncio
import logging
import os

from inspectio.v3.iter4_dynamo_wal.aws_clients import (
    aioboto3_session,
    botocore_high_throughput_config,
    session_kwargs,
)
from inspectio.v3.iter4_dynamo_wal.config import iter4_settings_from_env
from inspectio.v3.iter4_dynamo_wal.message_repository import MessageRepository
from inspectio.v3.iter4_dynamo_wal.sender import MockSmsSender
from inspectio.v3.iter4_dynamo_wal.sharding import (
    shards_owned_by_worker,
    worker_index_from_hostname,
)
from inspectio.v3.iter4_dynamo_wal.wal_buffer import WalBuffer
from inspectio.v3.iter4_dynamo_wal.worker.recovery import load_heap_from_dynamo
from inspectio.v3.iter4_dynamo_wal.worker.scheduler_loop import WorkerScheduler

logger = logging.getLogger(__name__)


async def _async_main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = iter4_settings_from_env()
    if not settings.s3_bucket:
        raise RuntimeError("INSPECTIO_V3_ITER4_S3_BUCKET is required for worker WAL")

    hostname = os.environ.get("HOSTNAME", "worker-0")
    if "INSPECTIO_V3_ITER4_WORKER_INDEX" in os.environ:
        worker_index = int(os.environ["INSPECTIO_V3_ITER4_WORKER_INDEX"])
    else:
        worker_index = worker_index_from_hostname(hostname)
    wal_writer_id = os.environ.get(
        "INSPECTIO_V3_ITER4_WAL_WRITER_ID",
        hostname.replace(".", "-"),
    )
    owned_shards = shards_owned_by_worker(
        worker_index,
        total_workers=settings.total_workers,
        total_shards=settings.total_shards,
    )
    logger.info(
        "worker starting hostname=%s index=%s shards=%s wal_id=%s",
        hostname,
        worker_index,
        owned_shards,
        wal_writer_id,
    )

    session = aioboto3_session()
    config = botocore_high_throughput_config()
    base_kw = session_kwargs(
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
    )
    reconcile_sec = settings.reconcile_interval_ms / 1000.0

    async with session.client("dynamodb", config=config, **base_kw) as ddb_client:
        async with session.client("s3", config=config, **base_kw) as s3_client:
            repo = MessageRepository(
                client=ddb_client,
                table_name=settings.dynamodb_table_name,
                gsi_scheduling_index_name=settings.gsi_scheduling_index_name,
            )
            wal = WalBuffer(
                writer_id=wal_writer_id,
                bucket=settings.s3_bucket,
                wal_prefix=settings.s3_wal_prefix,
                flush_interval_sec=settings.wal_flush_interval_sec,
            )
            wal.attach_s3_client(s3_client)
            wal.start_background()

            heap: list[tuple[int, str]] = []
            scheduled_ids: set[str] = set()
            loaded = await load_heap_from_dynamo(
                repo=repo,
                shard_ids=owned_shards,
                heap=heap,
                scheduled_ids=scheduled_ids,
            )
            logger.info("recovery loaded %s pending rows into heap", loaded)

            scheduler = WorkerScheduler(
                repo=repo,
                sender=MockSmsSender(),
                wal=wal,
                owned_shard_ids=owned_shards,
                reconcile_interval_sec=reconcile_sec,
            )
            scheduler.adopt_state(heap, scheduled_ids)
            try:
                await scheduler.run_forever()
            finally:
                await wal.stop()


def run() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    run()
