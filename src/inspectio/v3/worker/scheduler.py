"""Per-messageId lock, absolute deadlines, try_send → outcomes (P4 §4.5–4.7)."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from inspectio.v3.assignment_surface import Message
from inspectio.v3.domain.retry_schedule import attempt_deadline_ms
from inspectio.v3.outcomes.protocol import OutcomesWritePort
from inspectio.v3.persistence_emitter.noop import NoopPersistenceEventEmitter
from inspectio.v3.persistence_emitter.protocol import PersistenceEventEmitter
from inspectio.v3.persistence_recovery.bootstrap import RecoveryPendingSendUnit
from inspectio.v3.schemas.send_unit import SendUnitV1
from inspectio.v3.worker.metrics import SendWorkerMetrics
from inspectio.v3.worker.state import ActiveSendUnit

_log = logging.getLogger(__name__)


class SendScheduler:
    """Per-id ``asyncio.Lock``; ~500 ms wakeup scans due work (PDF NFR time)."""

    def __init__(
        self,
        *,
        clock_ms: Callable[[], int],
        try_send: Callable[[Message], bool]
        | Callable[[Message], Awaitable[bool]]
        | Callable[[Message], Coroutine[Any, Any, bool]],
        outcomes: OutcomesWritePort,
        delete_sqs_message: Callable[[str], Awaitable[None]],
        metrics: SendWorkerMetrics,
        persistence_emitter: PersistenceEventEmitter | None = None,
        persist_terminal_stub: Callable[[dict[str, Any]], Awaitable[None]]
        | None = None,
    ) -> None:
        self._clock_ms = clock_ms
        self._try_send_fn = try_send
        self._outcomes = outcomes
        self._delete_sqs = delete_sqs_message
        self._metrics = metrics
        self._persistence_emitter = persistence_emitter or NoopPersistenceEventEmitter()
        self._persist_terminal_stub = persist_terminal_stub
        self._active: dict[str, ActiveSendUnit] = {}
        self._terminal_message_ids: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._outcomes_tasks: set[asyncio.Task[None]] = set()

    def _lock(self, message_id: str) -> asyncio.Lock:
        if message_id not in self._locks:
            self._locks[message_id] = asyncio.Lock()
        return self._locks[message_id]

    def seed_recovered_terminal_ids(self, message_ids: set[str]) -> None:
        self._terminal_message_ids |= message_ids

    def seed_recovered_pending(
        self, pending_units: list[RecoveryPendingSendUnit]
    ) -> None:
        for pending in pending_units:
            if pending.message_id in self._terminal_message_ids:
                continue
            if pending.message_id in self._active:
                continue
            self._active[pending.message_id] = ActiveSendUnit(
                message_id=pending.message_id,
                body=pending.body,
                received_at_ms=pending.received_at_ms,
                batch_correlation_id=pending.batch_correlation_id,
                trace_id=pending.trace_id,
                shard=pending.shard,
                receipt_handle=None,
                completed_try_sends=pending.attempt_count,
            )

    async def flush_async_writes(self) -> None:
        """Drain in-flight best-effort outcomes writes (tests/shutdown)."""
        if not self._outcomes_tasks:
            return
        await asyncio.gather(*self._outcomes_tasks, return_exceptions=True)

    async def _emit_persist_stub(
        self,
        *,
        message_id: str,
        terminal_status: str,
        attempt_count: int,
        final_timestamp_ms: int,
        reason: str | None,
        trace_id: str,
        batch_correlation_id: str,
        shard: int,
    ) -> None:
        stub = self._persist_terminal_stub
        if stub is None:
            return
        payload: dict[str, Any] = {
            "schemaVersion": 1,
            "kind": "MessageTerminalV1",
            "messageId": message_id,
            "terminalStatus": terminal_status,
            "attemptCount": attempt_count,
            "finalTimestampMs": final_timestamp_ms,
            "reason": reason,
            "traceId": trace_id,
            "batchCorrelationId": batch_correlation_id,
            "shard": shard,
        }
        await stub(payload)

    def _schedule_outcomes_write(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
        reason: str | None,
    ) -> None:
        task = asyncio.create_task(
            self._record_outcome_best_effort(
                message_id=message_id,
                attempt_count=attempt_count,
                final_timestamp_ms=final_timestamp_ms,
                reason=reason,
            )
        )
        self._outcomes_tasks.add(task)
        self._metrics.outcomes_write_submitted += 1
        task.add_done_callback(self._on_outcomes_write_done)

    def _on_outcomes_write_done(self, task: asyncio.Task[None]) -> None:
        self._outcomes_tasks.discard(task)
        if task.cancelled():
            self._metrics.outcomes_write_errors += 1
            _log.warning("outcomes write task cancelled")
            return
        exc = task.exception()
        if exc is None:
            return
        self._metrics.outcomes_write_errors += 1
        _log.warning("outcomes write failed: %s", exc)

    async def _record_outcome_best_effort(
        self,
        *,
        message_id: str,
        attempt_count: int,
        final_timestamp_ms: int,
        reason: str | None,
    ) -> None:
        if reason is None:
            await self._outcomes.record_success(
                message_id=message_id,
                attempt_count=attempt_count,
                final_timestamp_ms=final_timestamp_ms,
            )
            return
        await self._outcomes.record_failed(
            message_id=message_id,
            attempt_count=attempt_count,
            final_timestamp_ms=final_timestamp_ms,
            reason=reason,
        )

    async def ingest_send_unit_sqs_message(self, sqs_message: dict[str, str]) -> None:
        """Parse body; dedupe duplicate SQS deliveries by ``messageId``."""
        receipt = sqs_message["ReceiptHandle"]
        unit = SendUnitV1.model_validate_json(sqs_message["Body"])
        mid = unit.message_id

        if mid in self._terminal_message_ids:
            await self._delete_sqs(receipt)
            return
        if mid in self._active:
            await self._delete_sqs(receipt)
            return

        self._active[mid] = ActiveSendUnit(
            message_id=mid,
            body=unit.body,
            received_at_ms=unit.received_at_ms,
            batch_correlation_id=unit.batch_correlation_id,
            trace_id=unit.trace_id,
            shard=unit.shard,
            receipt_handle=receipt,
            completed_try_sends=int(unit.attempts_completed),
        )

    async def wakeup_scan_due(self) -> None:
        """Multiplex with receive loop: cheap scan + parallel due processing."""
        now = self._clock_ms()
        tasks: list[asyncio.Task[None]] = []
        for mid in list(self._active.keys()):
            w = self._active.get(mid)
            if w is None:
                continue
            attempt_no = w.completed_try_sends + 1
            if attempt_no > 6:
                continue
            due = attempt_deadline_ms(w.received_at_ms, attempt_no)
            if now >= due:
                tasks.append(asyncio.create_task(self._process_due(mid)))
        if tasks:
            await asyncio.gather(*tasks)

    async def _process_due(self, mid: str) -> None:
        """Run every due try_send for this id (catch-up if clock jumped; never before deadline)."""
        while True:
            receipt_to_delete: str | None = None
            async with self._lock(mid):
                w = self._active.get(mid)
                if w is None:
                    return
                now = self._clock_ms()
                attempt_no = w.completed_try_sends + 1
                if attempt_no > 6:
                    return
                due = attempt_deadline_ms(w.received_at_ms, attempt_no)
                if now < due:
                    return

                msg = Message(message_id=mid, body=w.body)
                ok = await _call_try_send(self._try_send_fn, msg)
                w.completed_try_sends += 1
                ts = self._clock_ms()

                if ok:
                    ac = w.completed_try_sends
                    sh = w.shard
                    trace_id = w.trace_id
                    batch_correlation_id = w.batch_correlation_id
                    await self._persistence_emitter.emit_attempt_result(
                        trace_id=trace_id,
                        batch_correlation_id=batch_correlation_id,
                        message_id=mid,
                        shard=sh,
                        body=w.body,
                        received_at_ms=w.received_at_ms,
                        attempt_count=ac,
                        attempt_ok=True,
                        status="success",
                        next_due_at_ms=None,
                    )
                    await self._persistence_emitter.emit_terminal(
                        trace_id=trace_id,
                        batch_correlation_id=batch_correlation_id,
                        message_id=mid,
                        shard=sh,
                        body=w.body,
                        received_at_ms=w.received_at_ms,
                        attempt_count=ac,
                        status="success",
                        final_timestamp_ms=ts,
                        reason=None,
                    )
                    await self._emit_persist_stub(
                        message_id=mid,
                        terminal_status="success",
                        attempt_count=ac,
                        final_timestamp_ms=ts,
                        reason=None,
                        trace_id=trace_id,
                        batch_correlation_id=batch_correlation_id,
                        shard=sh,
                    )
                    receipt_to_delete = w.receipt_handle
                    self._terminal_message_ids.add(mid)
                    del self._active[mid]
                    self._metrics.send_ok += 1
                    self._schedule_outcomes_write(
                        message_id=mid,
                        attempt_count=ac,
                        final_timestamp_ms=ts,
                        reason=None,
                    )
                    _log.debug(
                        "send_ok messageId=%s traceId=%s batchCorrelationId=%s "
                        "attempts=%s shard=%s",
                        mid,
                        trace_id,
                        batch_correlation_id,
                        ac,
                        sh,
                    )
                elif w.completed_try_sends >= 6:
                    sh = w.shard
                    trace_id = w.trace_id
                    batch_correlation_id = w.batch_correlation_id
                    await self._persistence_emitter.emit_attempt_result(
                        trace_id=trace_id,
                        batch_correlation_id=batch_correlation_id,
                        message_id=mid,
                        shard=sh,
                        body=w.body,
                        received_at_ms=w.received_at_ms,
                        attempt_count=6,
                        attempt_ok=False,
                        status="failed",
                        next_due_at_ms=None,
                    )
                    await self._persistence_emitter.emit_terminal(
                        trace_id=trace_id,
                        batch_correlation_id=batch_correlation_id,
                        message_id=mid,
                        shard=sh,
                        body=w.body,
                        received_at_ms=w.received_at_ms,
                        attempt_count=6,
                        status="failed",
                        final_timestamp_ms=ts,
                        reason="max_try_send_failures",
                    )
                    await self._emit_persist_stub(
                        message_id=mid,
                        terminal_status="failed",
                        attempt_count=6,
                        final_timestamp_ms=ts,
                        reason="max_try_send_failures",
                        trace_id=trace_id,
                        batch_correlation_id=batch_correlation_id,
                        shard=sh,
                    )
                    receipt_to_delete = w.receipt_handle
                    self._terminal_message_ids.add(mid)
                    del self._active[mid]
                    self._metrics.send_fail += 1
                    self._schedule_outcomes_write(
                        message_id=mid,
                        attempt_count=6,
                        final_timestamp_ms=ts,
                        reason="max_try_send_failures",
                    )
                    _log.debug(
                        "send_fail messageId=%s traceId=%s batchCorrelationId=%s shard=%s",
                        mid,
                        trace_id,
                        batch_correlation_id,
                        sh,
                    )
                else:
                    ac = w.completed_try_sends
                    next_due = attempt_deadline_ms(w.received_at_ms, ac + 1)
                    await self._persistence_emitter.emit_attempt_result(
                        trace_id=w.trace_id,
                        batch_correlation_id=w.batch_correlation_id,
                        message_id=mid,
                        shard=w.shard,
                        body=w.body,
                        received_at_ms=w.received_at_ms,
                        attempt_count=ac,
                        attempt_ok=False,
                        status="pending",
                        next_due_at_ms=next_due,
                    )

            if receipt_to_delete is not None:
                await self._delete_sqs(receipt_to_delete)
                return


async def _call_try_send(
    fn: Callable[[Message], bool]
    | Callable[[Message], Awaitable[bool]]
    | Callable[[Message], Coroutine[Any, Any, bool]],
    message: Message,
) -> bool:
    result = fn(message)
    if inspect.isawaitable(result):
        return bool(await result)
    return bool(result)
