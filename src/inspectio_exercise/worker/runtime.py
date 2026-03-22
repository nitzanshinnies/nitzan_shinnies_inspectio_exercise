"""Shard-scoped scheduler entrypoint (plans/CORE_LIFECYCLE.md).

Details: README.md **Worker env**. Implementation: ``due_work_queue``, ``pending_discovery``,
``message_dispatch``, ``lifecycle_transitions``, ``worker_loop``.
"""

from __future__ import annotations

import asyncio
import json
from functools import partial

import httpx

from inspectio_exercise.domain.sharding import (
    owned_shard_ids,
    pod_index_from_hostname,
    shard_id_for_message,
)
from inspectio_exercise.worker import clocks
from inspectio_exercise.worker.config import (
    PERSISTENCE_READ_BASE_DELAY_SEC,
    PERSISTENCE_READ_MAX_ATTEMPTS,
    TERMINAL_LOOKBACK_HOURS,
    WORKER_TICK_INTERVAL_SEC,
    WorkerSettings,
)
from inspectio_exercise.worker.due_work_queue import DueWorkQueue
from inspectio_exercise.worker.lifecycle_transitions import LifecycleTransitions
from inspectio_exercise.worker.message_dispatch import MessageDispatch
from inspectio_exercise.worker.outcome_notifier import OutcomeNotifier
from inspectio_exercise.worker.pending_delete import delete_pending_best_effort
from inspectio_exercise.worker.pending_discovery import discover_owned_pending
from inspectio_exercise.worker.pending_record import (
    is_valid_pending_row,
    message_id_from_pending_key,
)
from inspectio_exercise.worker.persistence_port import PersistenceAsyncPort
from inspectio_exercise.worker.retrying_persistence import RetryingPersistence
from inspectio_exercise.worker.terminal_scanner import TerminalScanner
from inspectio_exercise.worker.worker_loop import run_forever_with_tick_interval


class WorkerRuntime:
    """Owned-shard pending discovery, min-heap due selection, concurrent sends per tick."""

    def __init__(
        self,
        *,
        notify_client: httpx.AsyncClient,
        persistence: PersistenceAsyncPort,
        persistence_read_backoff_sec: float | None = None,
        persistence_read_max_attempts: int | None = None,
        settings: WorkerSettings,
        sms_client: httpx.AsyncClient,
        terminal_lookback_hours: int | None = None,
        tick_interval_sec: float | None = None,
    ) -> None:
        persist = RetryingPersistence(
            persistence,
            base_delay_sec=(
                persistence_read_backoff_sec
                if persistence_read_backoff_sec is not None
                else PERSISTENCE_READ_BASE_DELAY_SEC
            ),
            max_attempts=(
                persistence_read_max_attempts
                if persistence_read_max_attempts is not None
                else PERSISTENCE_READ_MAX_ATTEMPTS
            ),
        )
        lookback = (
            terminal_lookback_hours
            if terminal_lookback_hours is not None
            else TERMINAL_LOOKBACK_HOURS
        )
        self._persist = persist
        self._queue = DueWorkQueue()
        self._message_locks: dict[str, asyncio.Lock] = {}
        self._total_shards = settings.total_shards
        self._owned = owned_shard_ids(
            pod_index_from_hostname(settings.hostname),
            settings.shards_per_pod,
            settings.total_shards,
        )
        self._tick_interval = (
            tick_interval_sec if tick_interval_sec is not None else WORKER_TICK_INTERVAL_SEC
        )
        self._sms = sms_client
        del_pending = partial(delete_pending_best_effort, persist)
        scanner = TerminalScanner(persist, lookback)
        outcomes = OutcomeNotifier(notify_client)
        self._lifecycle = LifecycleTransitions(
            delete_pending_best_effort=del_pending,
            drop_locked=self._queue.drop_locked,
            lock=self._queue.lock,
            outcomes=outcomes,
            persist=persist,
            records=self._queue.records,
            schedule_locked=self._queue.schedule_locked,
            scanner=scanner,
            total_shards=settings.total_shards,
        )
        self._dispatch = MessageDispatch(
            delete_pending=del_pending,
            lifecycle=self._lifecycle,
            message_lock_for=self._message_lock_for,
            persist=persist,
            queue=self._queue,
            scanner=scanner,
            sms=sms_client,
        )

    def _message_lock_for(self, message_id: str) -> asyncio.Lock:
        lock = self._message_locks.get(message_id)
        if lock is None:
            lock = asyncio.Lock()
            self._message_locks[message_id] = lock
        return lock

    async def activate_pending_now(self, pending_key: str) -> str:
        """Run attempt logic immediately for ``pending_key`` if this pod owns the shard.

        Used by the public API for assignment **attempt #1 at 0s** semantics. Returns a short
        status token: ``processed``, ``not_owner``, ``missing``, ``invalid``.
        """
        mid = message_id_from_pending_key(pending_key)
        if mid is None:
            return "invalid"
        shard = shard_id_for_message(mid, self._total_shards)
        if shard not in self._owned:
            return "not_owner"
        async with self._message_lock_for(mid):
            try:
                raw = await self._persist.get_object(pending_key)
            except KeyError:
                return "missing"
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return "invalid"
            if not is_valid_pending_row(mid, data):
                return "invalid"
            await self._dispatch.handle_one_core(mid, dict(data), pending_key)
        return "processed"

    async def run_forever(self, stop: asyncio.Event) -> None:
        await run_forever_with_tick_interval(self.run_tick, self._tick_interval, stop)

    async def run_tick(self) -> None:
        await discover_owned_pending(self._owned, self._persist, self._queue)
        due = await self._queue.collect_due(clocks.now_ms())
        if not due:
            return
        await asyncio.gather(
            *(self._dispatch.handle_one(mid, dict(rec), key) for mid, rec, key in due)
        )


__all__ = ["WorkerRuntime", "message_id_from_pending_key"]
