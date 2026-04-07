"""Persistence writer process entrypoint (P12.3)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from collections.abc import Awaitable, Callable

import aioboto3

from inspectio.v3.persistence_transport.sqs_consumer import (
    SqsPersistenceTransportConsumer,
)
from inspectio.v3.persistence_writer.s3_store import S3PersistenceObjectStore
from inspectio.v3.persistence_writer.writer import BufferedPersistenceWriter
from inspectio.v3.schemas.persistence_event import PersistenceEventV1
from inspectio.v3.settings import V3PersistenceWriterSettings
from inspectio.v3.sqs.boto_config import augment_client_kwargs_with_v3_config

_log = logging.getLogger(__name__)
MILLISECONDS_PER_SECOND = 1000
ACK_QUEUE_BLOCK_SLEEP_SEC = 0.005
ACK_BATCH_MAX_EVENTS = 1_000
ACK_SCHEDULE_MAX_INFLIGHT = 32


@dataclass(slots=True)
class QueueOldestAgeSample:
    age_ms: int = 0
    sampled_at_ms: int = 0
    last_attempted_at_ms: int = 0


def _ack_counts(events: list[PersistenceEventV1]) -> dict[int, int]:
    counts: dict[int, int] = defaultdict(int)
    for event in events:
        counts[event.shard] += 1
    return counts


def _observe_ack_metrics_for_batch(
    *,
    writer: BufferedPersistenceWriter,
    events: list[PersistenceEventV1],
    latency_ms: int,
    now_ms: int,
) -> None:
    for shard, count in _ack_counts(events).items():
        writer.metrics.observe_ack_batch(
            shard=shard,
            events=count,
            latency_ms=latency_ms,
            now_ms=now_ms,
        )


async def _enqueue_ack_events(
    *,
    ack_queue: asyncio.Queue[PersistenceEventV1],
    events: list[PersistenceEventV1],
    metrics: object,
) -> None:
    for event in events:
        while ack_queue.full():
            metrics.observe_ack_queue_blocked_push()
            await asyncio.sleep(ACK_QUEUE_BLOCK_SLEEP_SEC)
        ack_queue.put_nowait(event)
        metrics.observe_ack_queue_depth(depth=ack_queue.qsize())


def _drain_ack_batch(
    *,
    ack_queue: asyncio.Queue[PersistenceEventV1],
    first: PersistenceEventV1,
    max_events: int = ACK_BATCH_MAX_EVENTS,
) -> list[PersistenceEventV1]:
    batch = [first]
    while len(batch) < max(1, max_events):
        try:
            batch.append(ack_queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return batch


def _drain_ack_queue_nowait(
    *,
    ack_queue: asyncio.Queue[PersistenceEventV1],
    max_events: int = ACK_BATCH_MAX_EVENTS,
) -> list[PersistenceEventV1]:
    try:
        first = ack_queue.get_nowait()
    except asyncio.QueueEmpty:
        return []
    return _drain_ack_batch(
        ack_queue=ack_queue,
        first=first,
        max_events=max_events,
    )


async def _flush_loop_iteration(
    *,
    writer: BufferedPersistenceWriter,
    writer_lock: asyncio.Lock,
    enqueue_for_ack: Callable[[list[PersistenceEventV1]], Awaitable[None]],
) -> bool:
    async with writer_lock:
        flushed = await writer.flush_due(force=False)
    writer.metrics.observe_flush_loop_iteration(noop=not flushed)
    if not flushed:
        return False
    await enqueue_for_ack(flushed)
    return True


async def _shutdown_flush_and_ack(
    *,
    writer: BufferedPersistenceWriter,
    writer_lock: asyncio.Lock,
    ack_queue: asyncio.Queue[PersistenceEventV1],
    ack_many_with_retry: Callable[[list[PersistenceEventV1]], Awaitable[int]],
    clock_ms: Callable[[], int],
) -> None:
    async with writer_lock:
        final_flushed = await writer.flush_due(force=True)
    if final_flushed:
        final_ack_latency_ms = await ack_many_with_retry(final_flushed)
        _observe_ack_metrics_for_batch(
            writer=writer,
            events=final_flushed,
            latency_ms=final_ack_latency_ms,
            now_ms=clock_ms(),
        )
    while True:
        batch = _drain_ack_queue_nowait(ack_queue=ack_queue)
        if not batch:
            break
        ack_latency_ms = await ack_many_with_retry(batch)
        _observe_ack_metrics_for_batch(
            writer=writer,
            events=batch,
            latency_ms=ack_latency_ms,
            now_ms=clock_ms(),
        )
        for _ in batch:
            ack_queue.task_done()
        writer.metrics.observe_ack_queue_depth(depth=ack_queue.qsize())


async def _maybe_refresh_queue_oldest_age(
    *,
    consumer: SqsPersistenceTransportConsumer,
    sample: QueueOldestAgeSample,
    now_ms: int,
    sample_interval_ms: int,
    timeout_sec: float,
) -> QueueOldestAgeSample:
    if (
        sample.last_attempted_at_ms > 0
        and now_ms - sample.last_attempted_at_ms < sample_interval_ms
    ):
        return sample
    sample.last_attempted_at_ms = now_ms
    try:
        sampled_age = await asyncio.wait_for(
            consumer.queue_oldest_age_ms(),
            timeout=timeout_sec,
        )
    except Exception:  # noqa: BLE001
        return sample
    if sampled_age is None:
        return sample
    sample.age_ms = max(0, sampled_age)
    sample.sampled_at_ms = now_ms
    return sample


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
    boto_kw = augment_client_kwargs_with_v3_config(client_kw)

    queue_url = settings.resolved_transport_queue_url()
    async with (
        session.client("sqs", **boto_kw) as sqs_client,
        session.client("s3", **boto_kw) as s3_client,
    ):
        consumer = SqsPersistenceTransportConsumer(
            client=sqs_client,
            queue_url=queue_url,
            wait_seconds=settings.writer_receive_wait_seconds,
            receive_max_events=settings.writer_receive_max_events,
            ack_delete_max_concurrency=settings.persistence_ack_delete_max_concurrency,
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
            flush_min_batch_events=settings.writer_flush_min_batch_events,
            flush_interval_ms=settings.writer_flush_interval_ms,
            checkpoint_every_n_flushes=settings.persistence_checkpoint_every_n_flushes,
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

        async def receive_many_timed() -> list[PersistenceEventV1]:
            recv_started = time.perf_counter()
            batch = await consumer.receive_many(
                max_events=settings.writer_receive_max_events,
            )
            writer.metrics.observe_receive_many_duration(
                duration_ms=int((time.perf_counter() - recv_started) * 1000),
            )
            return batch

        last_snapshot_ms = clock_ms()
        queue_age_sample = QueueOldestAgeSample()
        queue_age_sample_interval_ms = (
            settings.writer_observability_queue_age_sample_interval_sec
            * MILLISECONDS_PER_SECOND
        )

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

        ack_schedule_sem = asyncio.Semaphore(ACK_SCHEDULE_MAX_INFLIGHT)
        pending_scheduled_acks: set[asyncio.Task[None]] = set()

        def _remember_ack_task(task: asyncio.Task[None]) -> None:
            pending_scheduled_acks.add(task)

            def _forget(done: asyncio.Task[None]) -> None:
                pending_scheduled_acks.discard(done)

            task.add_done_callback(_forget)

        async def _emit_snapshot_if_due() -> None:
            nonlocal last_snapshot_ms
            snapshot_now = clock_ms()
            if (
                snapshot_now - last_snapshot_ms
                < settings.writer_observability_snapshot_interval_sec
                * MILLISECONDS_PER_SECOND
            ):
                return
            _log.info(
                "writer_snapshot %s",
                json.dumps(
                    writer.metrics.snapshot(now_ms=snapshot_now), sort_keys=True
                ),
            )
            last_snapshot_ms = snapshot_now

        if not settings.writer_pipeline_enable:
            writer.metrics.pipeline_mode = "legacy"
            while True:
                events = await receive_many_timed()
                now_ms = clock_ms()
                queue_age_sample = await _maybe_refresh_queue_oldest_age(
                    consumer=consumer,
                    sample=queue_age_sample,
                    now_ms=now_ms,
                    sample_interval_ms=queue_age_sample_interval_ms,
                    timeout_sec=settings.writer_observability_queue_age_timeout_sec,
                )
                writer.metrics.observe_transport_oldest_age(
                    shard=settings.writer_shard_id,
                    age_ms=queue_age_sample.age_ms,
                    sampled_at_ms=queue_age_sample.sampled_at_ms,
                    now_ms=now_ms,
                )
                writer.metrics.observe_poll(idle=not events)
                writer.metrics.observe_receive_loop_iteration()
                if events:
                    for shard, count in _ack_counts(events).items():
                        writer.metrics.observe_receive_batch(
                            shard=shard,
                            events=count,
                            now_ms=now_ms,
                        )
                    await writer.ingest_events(events)
                flushed = await writer.flush_due(force=False)
                writer.metrics.observe_flush_loop_iteration(noop=not flushed)
                if flushed:
                    frozen = list(flushed)

                    async def _legacy_ack_job() -> None:
                        async with ack_schedule_sem:
                            try:
                                ms = await ack_many_with_retry(frozen)
                                _observe_ack_metrics_for_batch(
                                    writer=writer,
                                    events=frozen,
                                    latency_ms=ms,
                                    now_ms=clock_ms(),
                                )
                            except Exception:  # noqa: BLE001
                                _log.exception(
                                    "persistence writer legacy ack failed batch_len=%s",
                                    len(frozen),
                                )

                    _remember_ack_task(asyncio.create_task(_legacy_ack_job()))
                await _emit_snapshot_if_due()
                if not events:
                    await asyncio.sleep(settings.writer_idle_sleep_sec)
            return

        writer.metrics.pipeline_mode = "decoupled_v1"
        writer_lock = asyncio.Lock()
        ack_queue: asyncio.Queue[PersistenceEventV1] = asyncio.Queue(
            maxsize=settings.writer_ack_queue_max_events
        )
        writer.metrics.observe_ack_queue_depth(depth=ack_queue.qsize())

        async def _enqueue_for_ack(events: list[PersistenceEventV1]) -> None:
            await _enqueue_ack_events(
                ack_queue=ack_queue,
                events=events,
                metrics=writer.metrics,
            )

        async def _receive_ingest_loop() -> None:
            while True:
                writer.metrics.observe_receive_loop_iteration()
                events = await receive_many_timed()
                now_ms = clock_ms()
                queue_age_sample_local = await _maybe_refresh_queue_oldest_age(
                    consumer=consumer,
                    sample=queue_age_sample,
                    now_ms=now_ms,
                    sample_interval_ms=queue_age_sample_interval_ms,
                    timeout_sec=settings.writer_observability_queue_age_timeout_sec,
                )
                queue_age_sample.age_ms = queue_age_sample_local.age_ms
                queue_age_sample.sampled_at_ms = queue_age_sample_local.sampled_at_ms
                queue_age_sample.last_attempted_at_ms = (
                    queue_age_sample_local.last_attempted_at_ms
                )
                writer.metrics.observe_transport_oldest_age(
                    shard=settings.writer_shard_id,
                    age_ms=queue_age_sample.age_ms,
                    sampled_at_ms=queue_age_sample.sampled_at_ms,
                    now_ms=now_ms,
                )
                writer.metrics.observe_poll(idle=not events)
                if events:
                    for shard, count in _ack_counts(events).items():
                        writer.metrics.observe_receive_batch(
                            shard=shard,
                            events=count,
                            now_ms=now_ms,
                        )
                    async with writer_lock:
                        await writer.ingest_events(events)
                else:
                    await asyncio.sleep(settings.writer_idle_sleep_sec)

        async def _flush_loop() -> None:
            while True:
                await _flush_loop_iteration(
                    writer=writer,
                    writer_lock=writer_lock,
                    enqueue_for_ack=_enqueue_for_ack,
                )
                await asyncio.sleep(settings.writer_flush_loop_sleep_ms / 1000.0)

        async def _ack_loop() -> None:
            while True:
                first = await ack_queue.get()
                batch = _drain_ack_batch(ack_queue=ack_queue, first=first)
                frozen = list(batch)

                async def _decoupled_ack_job() -> None:
                    async with ack_schedule_sem:
                        try:
                            ack_latency_ms = await ack_many_with_retry(frozen)
                            _observe_ack_metrics_for_batch(
                                writer=writer,
                                events=frozen,
                                latency_ms=ack_latency_ms,
                                now_ms=clock_ms(),
                            )
                        except Exception:  # noqa: BLE001
                            _log.exception(
                                "persistence writer decoupled ack failed batch_len=%s",
                                len(frozen),
                            )
                    for _ in frozen:
                        ack_queue.task_done()
                    writer.metrics.observe_ack_queue_depth(depth=ack_queue.qsize())

                _remember_ack_task(asyncio.create_task(_decoupled_ack_job()))

        async def _snapshot_loop() -> None:
            while True:
                await _emit_snapshot_if_due()
                await asyncio.sleep(
                    settings.writer_observability_snapshot_interval_sec / 2.0
                )

        tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(_flush_loop(), name="writer-flush"),
            asyncio.create_task(_ack_loop(), name="writer-ack"),
            asyncio.create_task(_snapshot_loop(), name="writer-snapshot"),
        ]
        for idx in range(settings.writer_receive_loop_parallelism):
            tasks.append(
                asyncio.create_task(
                    _receive_ingest_loop(),
                    name=f"writer-receive-{idx}",
                )
            )
        done: set[asyncio.Task[None]] = set()
        try:
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            # Stop background loops first, then perform explicit shutdown flush+ack.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if pending_scheduled_acks:
                await asyncio.gather(
                    *list(pending_scheduled_acks), return_exceptions=True
                )
            try:
                await _shutdown_flush_and_ack(
                    writer=writer,
                    writer_lock=writer_lock,
                    ack_queue=ack_queue,
                    ack_many_with_retry=ack_many_with_retry,
                    clock_ms=clock_ms,
                )
            except Exception:  # noqa: BLE001
                _log.exception("writer shutdown drain failed")


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
