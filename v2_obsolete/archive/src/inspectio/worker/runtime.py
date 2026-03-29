"""Async scheduler runtime: immediate path + 500ms wakeup ."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

import httpx

from inspectio.domain.schedule import next_due_ms
from inspectio.domain.sharding import owned_shard_range
from inspectio.ingest.schema import MessageIngestedV1
from inspectio.journal.writer import JournalWriter
from inspectio.models import FAILED_ATTEMPT_COUNT, Message
from inspectio.settings import Settings
from inspectio.sms.client import post_send

log = logging.getLogger("inspectio.worker.runtime")

RetryRuntimeStatus = Literal["pending", "success", "failed"]


@dataclass(slots=True)
class RuntimeMessageState:
    message_id: str
    shard_id: int
    to: str
    body: str
    arrival_ms: int
    next_attempt_index: int
    next_due_at_ms: int
    status: RetryRuntimeStatus


@dataclass(slots=True)
class TerminalPublishTask:
    message_id: str
    terminal_status: Literal["success", "failed"]
    attempt_count: int
    final_ts: int
    reason: str | None
    retries: int = 0


class WorkerRuntime:
    """Owns shard range, per-`messageId` locks, SMS + journal + outcomes."""

    def __init__(
        self,
        settings: Settings,
        journal: JournalWriter,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._settings = settings
        self._journal = journal
        self._http = http_client
        self._states: dict[str, RuntimeMessageState] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._shard_sem: dict[int, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(settings.max_parallel_sends_per_shard)
        )
        self._terminal_retry_q: asyncio.Queue[TerminalPublishTask] = asyncio.Queue()
        self._owned = owned_shard_range(
            settings.worker_index,
            settings.total_shards,
            settings.worker_replicas,
        )

    @property
    def owned_range(self) -> tuple[int, int]:
        return self._owned

    def owns_shard(self, shard_id: int) -> bool:
        start, end = self._owned
        return start <= shard_id < end

    def restore_snapshot_pending(self, items: list[dict]) -> None:
        """Hydrate pending messages from snapshot JSON ."""
        for row in items:
            mid = str(row["messageId"])
            st = RuntimeMessageState(
                message_id=mid,
                shard_id=int(row["shardId"]),
                to=str(row["to"]),
                body=str(row["body"]),
                arrival_ms=int(row["arrivalMs"]),
                next_attempt_index=int(row["nextAttemptIndex"]),
                next_due_at_ms=int(row["nextDueAtMs"]),
                status="pending",
            )
            self._states[mid] = st

    def pending_snapshot_rows(self) -> list[dict]:
        """Serialize pending states for snapshot."""
        rows: list[dict] = []
        for st in self._states.values():
            if st.status != "pending":
                continue
            rows.append(
                {
                    "messageId": st.message_id,
                    "shardId": st.shard_id,
                    "to": st.to,
                    "body": st.body,
                    "arrivalMs": st.arrival_ms,
                    "nextAttemptIndex": st.next_attempt_index,
                    "nextDueAtMs": st.next_due_at_ms,
                }
            )
        return rows

    def bootstrap_from_ingest(self, ingested: MessageIngestedV1) -> Message:
        """Register pending state after durable ingest; caller then invokes `new_message`."""
        to = ingested.payload.to or self._settings.default_to_e164
        now = int(time.time() * 1000)
        st = RuntimeMessageState(
            message_id=ingested.message_id,
            shard_id=ingested.shard_id,
            to=to,
            body=ingested.payload.body,
            arrival_ms=ingested.received_at_ms,
            next_attempt_index=0,
            next_due_at_ms=min(ingested.received_at_ms, now),
            status="pending",
        )
        self._states[ingested.message_id] = st
        return Message(message_id=st.message_id, to=st.to, body=st.body)

    async def dispatch_new_message(self, message: Message) -> None:
        """First send attempt after ingest (paired with `bootstrap_from_ingest`)."""
        try:
            await self.async_send(message)
        except Exception:
            log.exception("dispatch_new_message failed mid=%s", message.message_id)

    async def async_send(self, message: Message) -> bool:
        """Run one send attempt with full journal + SMS ."""
        async with self._locks[message.message_id]:
            st = self._states.get(message.message_id)
            if st is None or st.status != "pending":
                return False
            if int(time.time() * 1000) < st.next_due_at_ms:
                return False
            return await self._send_locked(st)

    async def _send_locked(self, st: RuntimeMessageState) -> bool:
        shard_id = st.shard_id
        attempt_index = st.next_attempt_index
        async with self._shard_sem[shard_id]:
            now = int(time.time() * 1000)
            r_attempt = await self._journal.build_record(
                shard_id,
                record_type="SEND_ATTEMPTED",
                message_id=st.message_id,
                ts_ms=now,
                payload={"attemptIndex": attempt_index},
            )
            await self._journal.append_record(r_attempt)

            ok, http_status, err_cls = await post_send(
                self._http,
                self._settings,
                to=st.to,
                body=st.body,
                message_id=st.message_id,
                attempt_index=attempt_index,
            )
            now2 = int(time.time() * 1000)
            r_res = await self._journal.build_record(
                shard_id,
                record_type="SEND_RESULT",
                message_id=st.message_id,
                ts_ms=now2,
                payload={
                    "attemptIndex": attempt_index,
                    "ok": ok,
                    "httpStatus": http_status,
                    "errorClass": err_cls,
                },
            )
            await self._journal.append_record(r_res)

            if ok:
                ac = attempt_index + 1
                r_term = await self._journal.build_record(
                    shard_id,
                    record_type="TERMINAL",
                    message_id=st.message_id,
                    ts_ms=now2,
                    payload={
                        "status": "success",
                        "attemptCount": ac,
                    },
                )
                await self._journal.append_record(r_term)
                st.status = "success"
                log.info("terminal success mid=%s attempts=%s", st.message_id, ac)
                await self._post_terminal(
                    st.message_id,
                    terminal_status="success",
                    attempt_count=ac,
                    final_ts=now2,
                    reason=None,
                )
                return True

            if attempt_index < 5:
                completed = attempt_index + 1
                due = next_due_ms(st.arrival_ms, completed)
                r_next = await self._journal.build_record(
                    shard_id,
                    record_type="NEXT_DUE",
                    message_id=st.message_id,
                    ts_ms=now2,
                    payload={
                        "attemptCount": completed,
                        "nextDueAtMs": due,
                    },
                )
                await self._journal.append_record(r_next)
                st.next_attempt_index = attempt_index + 1
                st.next_due_at_ms = due
                log.debug(
                    "retry scheduled mid=%s next_attempt=%s due_ms=%s",
                    st.message_id,
                    st.next_attempt_index,
                    st.next_due_at_ms,
                )
                return False

            r_term = await self._journal.build_record(
                shard_id,
                record_type="TERMINAL",
                message_id=st.message_id,
                ts_ms=now2,
                payload={
                    "status": "failed",
                    "attemptCount": FAILED_ATTEMPT_COUNT,
                    "reason": "sms_exhausted",
                },
            )
            await self._journal.append_record(r_term)
            st.status = "failed"
            log.info(
                "terminal failed mid=%s attempts=%s",
                st.message_id,
                FAILED_ATTEMPT_COUNT,
            )
            await self._post_terminal(
                st.message_id,
                terminal_status="failed",
                attempt_count=FAILED_ATTEMPT_COUNT,
                final_ts=now2,
                reason="sms_exhausted",
            )
            return False

    async def _post_terminal_once(self, task: TerminalPublishTask) -> bool:
        base = self._settings.notification_base_url.rstrip("/")
        url = f"{base}/internal/v1/outcomes/terminal"
        payload = {
            "messageId": task.message_id,
            "terminalStatus": task.terminal_status,
            "attemptCount": task.attempt_count,
            "finalTimestampMs": task.final_ts,
            "reason": task.reason,
        }
        await self._http.post(url, json=payload, timeout=10.0)
        return True

    async def _post_terminal(
        self,
        message_id: str,
        *,
        terminal_status: Literal["success", "failed"],
        attempt_count: int,
        final_ts: int,
        reason: str | None,
    ) -> None:
        task = TerminalPublishTask(
            message_id=message_id,
            terminal_status=terminal_status,
            attempt_count=attempt_count,
            final_ts=final_ts,
            reason=reason,
        )
        try:
            await self._post_terminal_once(task)
        except httpx.HTTPError as exc:
            log.warning("terminal notify failed mid=%s err=%s", message_id, exc)
            await self._terminal_retry_q.put(task)

    async def terminal_retry_loop(self, stop: asyncio.Event) -> None:
        """Best-effort retry for terminal outcome publication."""
        while not stop.is_set():
            try:
                task = await asyncio.wait_for(self._terminal_retry_q.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                await self._post_terminal_once(task)
            except httpx.HTTPError as exc:
                retries = task.retries + 1
                if retries <= 20:
                    backoff = min(2 ** min(retries, 6), 30)
                    await asyncio.sleep(backoff)
                    await self._terminal_retry_q.put(
                        TerminalPublishTask(
                            message_id=task.message_id,
                            terminal_status=task.terminal_status,
                            attempt_count=task.attempt_count,
                            final_ts=task.final_ts,
                            reason=task.reason,
                            retries=retries,
                        )
                    )
                else:
                    log.error(
                        "terminal notify dropped after retries mid=%s err=%s",
                        task.message_id,
                        exc,
                    )

    async def wakeup_due(self) -> None:
        """Dispatch due pending messages (tick path)."""
        now = int(time.time() * 1000)
        pending_ids = [
            mid
            for mid, st in self._states.items()
            if st.status == "pending" and st.next_due_at_ms <= now
        ]
        for mid in pending_ids:
            st = self._states.get(mid)
            if st is None or st.status != "pending":
                continue
            msg = Message(message_id=st.message_id, to=st.to, body=st.body)
            asyncio.create_task(self.async_send(msg))
