"""P6 scheduler runtime: immediate queue, due dispatch, per-message locks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from inspectio.domain.schedule import is_send_due, next_due_ms
from inspectio.journal.records import JournalRecordV1
from inspectio.models import Message, RetryStateV1

MAX_ATTEMPTS = 6


class SmsSender(Protocol):
    """SMS sender protocol used by runtime."""

    async def send(self, message: Message, attempt_index: int) -> bool:
        """Return True on success, False on failure."""


@dataclass(frozen=True, slots=True)
class MessageContext:
    message: Message
    shard_id: int


class InMemorySchedulerRuntime:
    """Deterministic in-memory runtime used by P6 surface and tests."""

    def __init__(self, *, now_ms: Callable[[], int], sms_sender: SmsSender) -> None:
        self._now_ms = now_ms
        self._sms_sender = sms_sender
        self._state: dict[str, RetryStateV1] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._context_by_message_id: dict[str, MessageContext] = {}
        self._arrival_ms: dict[str, int] = {}
        self._next_record_index = 1
        self.journal: list[JournalRecordV1] = []

    async def new_message(self, message: Message, *, shard_id: int = 0) -> None:
        arrival = self._now_ms()
        self._context_by_message_id[message.message_id] = MessageContext(
            message=message,
            shard_id=shard_id,
        )
        self._arrival_ms[message.message_id] = arrival
        self._state[message.message_id] = RetryStateV1(
            message_id=message.message_id,
            attempt_count=0,
            next_due_at_ms=arrival,
            status="pending",
            last_error=None,
            payload={"to": message.to, "body": message.body},
            updated_at_ms=arrival,
        )
        await self._attempt_if_due(
            message.message_id, now_ms=arrival, dispatch_reason=None
        )

    async def wakeup(self) -> None:
        now_ms = self._now_ms()
        candidates = [
            message_id
            for message_id, state in self._state.items()
            if state.status == "pending" and is_send_due(now_ms, state.next_due_at_ms)
        ]
        await asyncio.gather(
            *(
                self._attempt_if_due(
                    message_id,
                    now_ms=now_ms,
                    dispatch_reason="tick",
                )
                for message_id in candidates
            )
        )

    async def _attempt_if_due(
        self,
        message_id: str,
        *,
        now_ms: int,
        dispatch_reason: str | None,
    ) -> None:
        lock = self._locks.setdefault(message_id, asyncio.Lock())
        async with lock:
            state = self._state.get(message_id)
            if state is None or state.status != "pending":
                return
            if not is_send_due(now_ms, state.next_due_at_ms):
                return
            context = self._context_by_message_id[message_id]
            if dispatch_reason is not None:
                self._append_record(
                    record_type="DISPATCH_SCHEDULED",
                    message_id=message_id,
                    shard_id=context.shard_id,
                    ts_ms=now_ms,
                    payload={"reason": dispatch_reason},
                )
            attempt_index = state.attempt_count
            self._append_record(
                record_type="SEND_ATTEMPTED",
                message_id=message_id,
                shard_id=context.shard_id,
                ts_ms=now_ms,
                payload={"attemptIndex": attempt_index},
            )
            ok, error_class = await self._safe_send(
                context.message,
                attempt_index=attempt_index,
            )
            self._append_record(
                record_type="SEND_RESULT",
                message_id=message_id,
                shard_id=context.shard_id,
                ts_ms=now_ms,
                payload={
                    "attemptIndex": attempt_index,
                    "ok": ok,
                    "httpStatus": None,
                    "errorClass": error_class,
                },
            )
            completed_attempt_count = attempt_index + 1
            if ok:
                self._state[message_id] = RetryStateV1(
                    message_id=message_id,
                    attempt_count=completed_attempt_count,
                    next_due_at_ms=state.next_due_at_ms,
                    status="success",
                    last_error=None,
                    payload=state.payload,
                    updated_at_ms=now_ms,
                )
                self._append_record(
                    record_type="TERMINAL",
                    message_id=message_id,
                    payload={
                        "status": "success",
                        "attemptCount": completed_attempt_count,
                    },
                    shard_id=context.shard_id,
                    ts_ms=now_ms,
                )
                return
            if completed_attempt_count >= MAX_ATTEMPTS:
                self._state[message_id] = RetryStateV1(
                    message_id=message_id,
                    attempt_count=MAX_ATTEMPTS,
                    next_due_at_ms=state.next_due_at_ms,
                    status="failed",
                    last_error=error_class,
                    payload=state.payload,
                    updated_at_ms=now_ms,
                )
                self._append_record(
                    record_type="TERMINAL",
                    message_id=message_id,
                    payload={
                        "status": "failed",
                        "attemptCount": MAX_ATTEMPTS,
                        "reason": error_class or "send_failed",
                    },
                    shard_id=context.shard_id,
                    ts_ms=now_ms,
                )
                return
            next_due = next_due_ms(
                self._arrival_ms[message_id], completed_attempt_count
            )
            self._state[message_id] = RetryStateV1(
                message_id=message_id,
                attempt_count=completed_attempt_count,
                next_due_at_ms=next_due,
                status="pending",
                last_error=error_class,
                payload=state.payload,
                updated_at_ms=now_ms,
            )
            self._append_record(
                record_type="NEXT_DUE",
                message_id=message_id,
                payload={
                    "attemptCount": completed_attempt_count,
                    "nextDueAtMs": next_due,
                },
                shard_id=context.shard_id,
                ts_ms=now_ms,
            )

    async def send_once(self, message: Message, *, attempt_index: int) -> bool:
        """Expose one adapter send for scheduler surface mapping (§25)."""
        ok, _ = await self._safe_send(message, attempt_index=attempt_index)
        return ok

    async def _safe_send(
        self, message: Message, *, attempt_index: int
    ) -> tuple[bool, str | None]:
        try:
            ok = await self._sms_sender.send(message, attempt_index)
            if ok:
                return True, None
            return False, "send_failed"
        except TimeoutError:
            return False, "connect_timeout"

    def journal_length(self) -> int:
        return len(self.journal)

    def journal_since(self, index: int) -> list[JournalRecordV1]:
        return self.journal[index:]

    def _append_record(
        self,
        *,
        record_type: str,
        message_id: str,
        shard_id: int,
        ts_ms: int,
        payload: dict[str, Any],
    ) -> None:
        self.journal.append(
            JournalRecordV1.model_validate(
                {
                    "v": 1,
                    "type": record_type,
                    "shardId": shard_id,
                    "messageId": message_id,
                    "tsMs": ts_ms,
                    "recordIndex": self._next_record_index,
                    "payload": payload,
                }
            )
        )
        self._next_record_index += 1
