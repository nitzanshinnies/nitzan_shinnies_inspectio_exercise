"""One due message: verify pending, reconcile terminal, or call mock SMS then lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
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
_DISPATCH_RETRY_BACKOFF_MS = 500
_TRACE_SAMPLE_MOD = 100
_TRACE_SAMPLE_HIT = 0


def _should_trace_message(message_id: str) -> bool:
    digest = hashlib.sha256(message_id.encode("utf-8")).digest()
    return (int.from_bytes(digest[:4], "big") % _TRACE_SAMPLE_MOD) == _TRACE_SAMPLE_HIT


class MessageDispatch:
    def __init__(
        self,
        *,
        delete_pending: Callable[[str], Awaitable[None]],
        lifecycle: LifecycleTransitions,
        message_lock_for: Callable[[str], asyncio.Lock],
        persist: RetryingPersistence,
        queue: DueWorkQueue,
        scanner: TerminalScanner,
        sms: httpx.AsyncClient,
    ) -> None:
        self._delete_pending = delete_pending
        self._lifecycle = lifecycle
        self._message_lock_for = message_lock_for
        self._persist = persist
        self._queue = queue
        self._scanner = scanner
        self._sms = sms

    async def handle_one(self, mid: str, rec: dict[str, Any], pending_key: str) -> None:
        async with self._message_lock_for(mid):
            await self.handle_one_core(mid, rec, pending_key)

    async def handle_one_core(self, mid: str, rec: dict[str, Any], pending_key: str) -> None:
        trace = _should_trace_message(mid)
        if trace:
            logger.info("dispatch phase=begin message_id=%s key=%s", mid, pending_key)
        try:
            await self._persist.get_object(pending_key)
            if trace:
                logger.info("dispatch phase=pending_exists message_id=%s", mid)
        except KeyError:
            async with self._queue.lock:
                self._queue.drop_locked(mid)
            if trace:
                logger.info("dispatch phase=pending_missing_drop message_id=%s", mid)
            return
        except Exception:
            logger.warning(
                "pending read failed for message_id=%s; rescheduling dispatch",
                mid,
                exc_info=True,
            )
            async with self._queue.lock:
                cur = self._queue.records.get(mid)
                if cur is not None:
                    cur["nextDueAt"] = clocks.now_ms() + _DISPATCH_RETRY_BACKOFF_MS
                    self._queue.schedule_locked(mid, int(cur["nextDueAt"]))
            if trace:
                logger.info("dispatch phase=pending_read_error_rescheduled message_id=%s", mid)
            return
        ac = int(rec["attemptCount"])
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
            if trace:
                logger.info("dispatch phase=invalid_payload_drop message_id=%s", mid)
            return
        should_fail = payload.get("shouldFail") is True
        try:
            if trace:
                logger.info("dispatch phase=sms_send_start message_id=%s", mid)
            status = await post_mock_send(
                self._sms,
                attempt_index=ac,
                body=body,
                message_id=mid,
                should_fail=should_fail,
                to=to,
            )
            if trace:
                logger.info("dispatch phase=sms_send_done message_id=%s status=%s", mid, status)
        except httpx.HTTPError:
            logger.warning(
                "mock sms transport error for message_id=%s; scheduling retry",
                mid,
                exc_info=True,
            )
            await self._lifecycle.transition_failure(mid, rec, pending_key)
            if trace:
                logger.info("dispatch phase=transition_failure_done message_id=%s", mid)
            return
        if is_successful_send(status):
            if trace:
                logger.info("dispatch phase=transition_success_start message_id=%s", mid)
            await self._lifecycle.transition_success(mid, rec, pending_key)
            if trace:
                logger.info("dispatch phase=transition_success_done message_id=%s", mid)
        else:
            if trace:
                logger.info("dispatch phase=transition_failure_start message_id=%s", mid)
            await self._lifecycle.transition_failure(mid, rec, pending_key)
            if trace:
                logger.info("dispatch phase=transition_failure_done message_id=%s", mid)
