"""L4 send worker: long-poll send shard + ~500 ms wakeup (P4)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aioboto3

from inspectio.v3.assignment_surface import Message
from inspectio.v3.outcomes.redis_store import RedisOutcomesStore
from inspectio.v3.settings import (
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = V3WorkerSettings()
    outcomes = RedisOutcomesStore.from_url(settings.redis_url)
    metrics = SendWorkerMetrics()
    session = aioboto3.Session()
    kw = sqs_client_kwargs_from_worker_settings(settings)

    def clock_ms() -> int:
        return int(time.time() * 1000)

    try_send = _try_send_factory(settings)

    async with session.client("sqs", **kw) as client:
        q = settings.send_queue_url
        persist_url = settings.persist_queue_url

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
            persist_terminal_stub=persist_terminal_stub,
        )

        async def receive_loop() -> None:
            while True:
                resp = await client.receive_message(
                    QueueUrl=q,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=20,
                )
                for msg in resp.get("Messages", []):
                    await scheduler.ingest_send_unit_sqs_message(msg)

        async def wakeup_loop() -> None:
            while True:
                await asyncio.sleep(0.5)
                await scheduler.wakeup_scan_due()

        _log.info("worker started queue=%s", q)
        await asyncio.gather(receive_loop(), wakeup_loop())


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
