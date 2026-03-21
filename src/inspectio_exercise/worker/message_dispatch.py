"""One due message: verify pending, reconcile terminal, or call mock SMS then lifecycle."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from inspectio_exercise.domain.sms_outcome import is_successful_send
from inspectio_exercise.worker import clocks
from inspectio_exercise.worker.due_work_queue import DueWorkQueue
from inspectio_exercise.worker.lifecycle_transitions import LifecycleTransitions
from inspectio_exercise.worker.mock_sms_client import post_mock_send
from inspectio_exercise.worker.retrying_persistence import RetryingPersistence
from inspectio_exercise.worker.terminal_scanner import TerminalScanner

logger = logging.getLogger(__name__)


class MessageDispatch:
    def __init__(
        self,
        *,
        delete_pending: Callable[[str], Awaitable[None]],
        lifecycle: LifecycleTransitions,
        persist: RetryingPersistence,
        queue: DueWorkQueue,
        scanner: TerminalScanner,
        sms: httpx.AsyncClient,
    ) -> None:
        self._delete_pending = delete_pending
        self._lifecycle = lifecycle
        self._persist = persist
        self._queue = queue
        self._scanner = scanner
        self._sms = sms

    async def handle_one(self, mid: str, rec: dict[str, Any], pending_key: str) -> None:
        try:
            await self._persist.get_object(pending_key)
        except KeyError:
            async with self._queue.lock:
                self._queue.drop_locked(mid)
            return
        now_ms = clocks.now_ms()
        existing = await self._scanner.find_existing(mid, now_ms)
        if existing is not None:
            outcome, terminal_key, body = existing
            await self._lifecycle.reconcile_from_terminal(
                mid,
                pending_key,
                body=body,
                outcome=outcome,
                terminal_key=terminal_key,
            )
            return
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        to = payload.get("to", "")
        body = payload.get("body", "")
        if not isinstance(to, str) or not isinstance(body, str):
            logger.warning(
                "invalid payload for message_id=%s — removing pending object and dropping scheduler state",
                mid,
            )
            await self._delete_pending(pending_key)
            async with self._queue.lock:
                self._queue.drop_locked(mid)
            return
        ac = int(rec["attemptCount"])
        status = await post_mock_send(
            self._sms,
            to=to,
            body=body,
            message_id=mid,
            attempt_index=ac,
        )
        if is_successful_send(status):
            await self._lifecycle.transition_success(mid, rec, pending_key)
        else:
            await self._lifecycle.transition_failure(mid, rec, pending_key)
