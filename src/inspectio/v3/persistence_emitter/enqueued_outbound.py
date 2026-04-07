"""Non-blocking L2 enqueued persistence outbound queue + batch flusher."""

from __future__ import annotations

import asyncio
import logging

from inspectio.v3.persistence_transport.protocol import PersistenceTransportProducer
from inspectio.v3.schemas.persistence_event import PersistenceEventV1

_log = logging.getLogger(__name__)

_ENQUEUE_SHUTDOWN = object()
_BATCH_MAX = 10
_FLUSH_INTERVAL_SEC = 0.05


class L2EnqueuedPersistenceOutboundQueue:
    """``put_nowait`` admission path; background task flushes via ``publish_many``."""

    def __init__(
        self,
        *,
        producer: PersistenceTransportProducer,
        batch_max: int = _BATCH_MAX,
        flush_interval_sec: float = _FLUSH_INTERVAL_SEC,
    ) -> None:
        self._producer = producer
        self._batch_max = max(1, min(10, batch_max))
        self._flush_interval_sec = max(0.001, flush_interval_sec)
        self._q: asyncio.Queue[PersistenceEventV1 | object] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._task = asyncio.create_task(self._run(), name="l2-persist-enqueued-flush")

    def put_nowait(self, event: PersistenceEventV1) -> None:
        self._q.put_nowait(event)

    async def stop(self) -> None:
        if not self._started:
            return
        await self._q.put(_ENQUEUE_SHUTDOWN)
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _log.exception("l2 persistence enqueued flush task failed")
            self._task = None
        self._started = False

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            first = await self._q.get()
            if first is _ENQUEUE_SHUTDOWN:
                await self._drain_remaining_after_shutdown()
                return
            assert isinstance(first, PersistenceEventV1)
            batch = [first]
            deadline = loop.time() + self._flush_interval_sec
            while len(batch) < self._batch_max:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    item = await asyncio.wait_for(self._q.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                if item is _ENQUEUE_SHUTDOWN:
                    await self._q.put(_ENQUEUE_SHUTDOWN)
                    break
                assert isinstance(item, PersistenceEventV1)
                batch.append(item)
            try:
                await self._producer.publish_many(batch)
            except Exception:  # noqa: BLE001
                _log.exception(
                    "l2 persistence enqueued flush publish_many failed batch_len=%s",
                    len(batch),
                )

    async def _drain_remaining_after_shutdown(self) -> None:
        pending: list[PersistenceEventV1] = []
        while True:
            try:
                item = self._q.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is _ENQUEUE_SHUTDOWN:
                continue
            assert isinstance(item, PersistenceEventV1)
            pending.append(item)
        for i in range(0, len(pending), self._batch_max):
            chunk = pending[i : i + self._batch_max]
            try:
                await self._producer.publish_many(chunk)
            except Exception:  # noqa: BLE001
                _log.exception(
                    "l2 persistence shutdown flush publish_many failed batch_len=%s",
                    len(chunk),
                )
