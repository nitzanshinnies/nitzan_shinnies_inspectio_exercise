"""L4 send worker: long-poll send shard + ~500 ms wakeup (P4)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import aioboto3

from inspectio.v3.assignment_surface import Message
from inspectio.v3.outcomes.null_store import NullOutcomesWriter
from inspectio.v3.outcomes.redis_store import RedisOutcomesStore
from inspectio.v3.persistence_emitter.noop import NoopPersistenceEventEmitter
from inspectio.v3.persistence_emitter.transport import TransportPersistenceEventEmitter
from inspectio.v3.persistence_transport.sqs_producer import (
    SqsPersistenceTransportProducer,
)
from inspectio.v3.settings import (
    V3PersistenceSettings,
    V3WorkerSettings,
    sqs_client_kwargs_from_worker_settings,
)
from inspectio.v3.worker.metrics import SendWorkerMetrics
from inspectio.v3.worker.scheduler import SendScheduler

_log = logging.getLogger(__name__)


def _try_send_factory(settings: V3WorkerSettings):
    if settings.try_send_always_succeed:

        def _ok(_m: Message) -> bool:
            return True

        return _ok

    def _fail(_m: Message) -> bool:
        return False

    return _fail


async def amain() -> None:
    _lvl_name = os.environ.get("INSPECTIO_V3_WORKER_LOG_LEVEL", "INFO").upper()
    _lvl = getattr(logging, _lvl_name, logging.INFO)
    logging.basicConfig(level=_lvl, format="%(levelname)s %(name)s %(message)s")
    settings = V3WorkerSettings()
    persistence_settings = V3PersistenceSettings()
    outcomes = (
        RedisOutcomesStore.from_url(settings.redis_url)
        if settings.worker_record_outcomes
        else NullOutcomesWriter()
    )
    persistence_emitter = NoopPersistenceEventEmitter()
    metrics = SendWorkerMetrics()
    session = aioboto3.Session()
    kw = sqs_client_kwargs_from_worker_settings(settings)

    def clock_ms() -> int:
        return int(time.time() * 1000)

    try_send = _try_send_factory(settings)

    async with session.client("sqs", **kw) as client:
        q = settings.send_queue_url
        persist_url = settings.persist_queue_url
        if (
            persistence_settings.persistence_emit_enabled
            and persistence_settings.persist_transport_queue_url
        ):
            producer = SqsPersistenceTransportProducer(
                queue_url=persistence_settings.persist_transport_queue_url,
                dlq_queue_url=persistence_settings.persist_transport_dlq_url,
                client=client,
                durability_mode=persistence_settings.persistence_durability_mode,
                max_attempts=persistence_settings.persist_transport_max_attempts,
                backoff_base_ms=persistence_settings.persist_transport_backoff_base_ms,
                backoff_max_ms=persistence_settings.persist_transport_backoff_max_ms,
                backoff_jitter_fraction=persistence_settings.persist_transport_backoff_jitter_fraction,
                max_inflight_events=persistence_settings.persist_transport_max_inflight_events,
                max_batch_events=persistence_settings.persist_transport_batch_max_events,
            )
            persistence_emitter = TransportPersistenceEventEmitter(
                producer=producer,
                clock_ms=clock_ms,
            )

        async def delete_rh(rh: str) -> None:
            await client.delete_message(QueueUrl=q, ReceiptHandle=rh)

        async def persist_terminal_stub(payload: dict[str, Any]) -> None:
            if not persist_url:
                return
            try:
                await client.send_message(
                    QueueUrl=persist_url,
                    MessageBody=json.dumps(payload),
                )
            except Exception as exc:
                _log.warning("L5 persist stub send failed: %s", exc)

        scheduler = SendScheduler(
            clock_ms=clock_ms,
            try_send=try_send,
            outcomes=outcomes,
            delete_sqs_message=delete_rh,
            metrics=metrics,
            persistence_emitter=persistence_emitter,
            persist_terminal_stub=persist_terminal_stub,
        )

        async def receive_loop() -> None:
            while True:
                resp = await client.receive_message(
                    QueueUrl=q,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=20,
                )
                msgs = resp.get("Messages", [])
                if msgs:
                    await asyncio.gather(
                        *[scheduler.ingest_send_unit_sqs_message(m) for m in msgs],
                    )

        wake_every = float(settings.worker_wakeup_sec)

        async def wakeup_loop() -> None:
            while True:
                await asyncio.sleep(wake_every)
                await scheduler.wakeup_scan_due()

        pollers = max(1, int(settings.worker_receive_pollers))
        receive_tasks = [asyncio.create_task(receive_loop()) for _ in range(pollers)]
        _log.info("worker started queue=%s pollers=%s", q, pollers)
        await asyncio.gather(*receive_tasks, wakeup_loop())


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
