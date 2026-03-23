"""Shard-scoped scheduler entrypoint (plans/CORE_LIFECYCLE.md).

Details: README.md **Worker env**. Implementation: ``due_work_queue``, ``pending_discovery``,
``message_dispatch``, ``lifecycle_transitions``, ``worker_loop``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from functools import partial
from typing import Any

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
from inspectio_exercise.worker.pending_record import message_id_from_pending_key
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
        self._max_parallel_handles = max(1, settings.max_parallel_handles)
        self._wake_scheduler = asyncio.Event()

    def _message_lock_for(self, message_id: str) -> asyncio.Lock:
        lock = self._message_locks.get(message_id)
        if lock is None:
            lock = asyncio.Lock()
            self._message_locks[message_id] = lock
        return lock

    async def _activate_pending_enqueue(self, pending_key: str, *, wake: bool) -> str:
        """Load pending JSON into the due queue; optional scheduler wake (API activation path)."""
        mid = message_id_from_pending_key(pending_key)
        if mid is None:
            return "invalid"
        shard = shard_id_for_message(mid, self._total_shards)
        if shard not in self._owned:
            return "not_owner"
        try:
            raw = await self._persist.get_object(pending_key)
        except KeyError:
            return "missing"
        ok = await self._queue.upsert_pending(mid, pending_key, raw)
        if not ok:
            return "invalid"
        if wake:
            self._wake_scheduler.set()
        return "scheduled"

    async def activate_pending_now(self, pending_key: str) -> str:
        """Enqueue ``pending_key`` for the next tick(s) and wake the scheduler (fast HTTP).

        Attempt #1 runs on ``run_tick`` — not inline with this handler — so the API is not
        blocked on mock SMS latency. Returns ``scheduled`` on success.
        """
        return await self._activate_pending_enqueue(pending_key, wake=True)

    async def activate_pending_batch(self, pending_keys: Sequence[str]) -> dict[str, int]:
        """Enqueue many keys; wake once if at least one row was scheduled."""
        accepted = 0
        not_owner = 0
        missing = 0
        invalid = 0
        for pk in pending_keys:
            st = await self._activate_pending_enqueue(pk, wake=False)
            if st == "scheduled":
                accepted += 1
            elif st == "not_owner":
                not_owner += 1
            elif st == "missing":
                missing += 1
            else:
                invalid += 1
        if accepted > 0:
            self._wake_scheduler.set()
        return {
            "accepted": accepted,
            "notOwner": not_owner,
            "missing": missing,
            "invalid": invalid,
        }

    async def run_forever(self, stop: asyncio.Event) -> None:
        await run_forever_with_tick_interval(
            self.run_tick,
            self._tick_interval,
            stop,
            wake=self._wake_scheduler,
        )

    async def run_tick(self) -> None:
        await discover_owned_pending(self._owned, self._persist, self._queue)
        due = await self._queue.collect_due(clocks.now_ms())
        if not due:
            return
        sem = asyncio.Semaphore(self._max_parallel_handles)

        async def _bounded(mid: str, rec: dict[str, Any], key: str) -> None:
            async with sem:
                await self._dispatch.handle_one(mid, dict(rec), key)

        await asyncio.gather(*(_bounded(mid, rec, key) for mid, rec, key in due))


__all__ = ["WorkerRuntime", "message_id_from_pending_key"]
