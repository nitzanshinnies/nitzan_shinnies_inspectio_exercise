"""500 ms ``wakeup()`` loop: monotonic pacing, heap due-set, concurrent ``send``, DDB updates.

Reconciliation pulls newly-due rows from the SchedulingIndex into the heap between ticks.
"""

from __future__ import annotations

import asyncio
import heapq
import time

from inspectio.v3.iter4_dynamo_wal.constants import (
    MAX_SEND_ATTEMPTS,
    STATUS_PENDING,
    TICK_INTERVAL_SEC,
)
from inspectio.v3.iter4_dynamo_wal.message_repository import (
    MessageRepository,
    epoch_ms,
    next_retry_due_ms,
)
from inspectio.v3.iter4_dynamo_wal.sender import SmsSender
from inspectio.v3.iter4_dynamo_wal.wal_buffer import WalBuffer


class WorkerScheduler:
    def __init__(
        self,
        *,
        repo: MessageRepository,
        sender: SmsSender,
        wal: WalBuffer,
        owned_shard_ids: list[str],
        reconcile_interval_sec: float,
    ) -> None:
        self._repo = repo
        self._sender = sender
        self._wal = wal
        self._shards = owned_shard_ids
        self._reconcile_interval_sec = reconcile_interval_sec
        self._heap: list[tuple[int, str]] = []
        self._scheduled_ids: set[str] = set()

    @property
    def heap(self) -> list[tuple[int, str]]:
        return self._heap

    @property
    def scheduled_ids(self) -> set[str]:
        return self._scheduled_ids

    def adopt_state(
        self,
        heap: list[tuple[int, str]],
        scheduled_ids: set[str],
    ) -> None:
        self._heap = heap
        self._scheduled_ids = scheduled_ids

    async def reconcile_once(self) -> None:
        now_ms = epoch_ms()
        for shard_id in self._shards:
            rows = await self._repo.load_due_pending_for_shard(
                shard_id,
                due_before_ms=now_ms,
            )
            for row in rows:
                mid = str(row["messageId"])
                if mid in self._scheduled_ids:
                    continue
                heapq.heappush(self._heap, (int(row["nextDueAt"]), mid))
                self._scheduled_ids.add(mid)

    async def _process_one(self, message_id: str) -> None:
        row = await self._repo.get_by_message_id(message_id)
        if row is None:
            return
        if str(row.get("status")) != STATUS_PENDING:
            return
        now_ms = epoch_ms()
        if int(row["nextDueAt"]) > now_ms:
            heapq.heappush(self._heap, (int(row["nextDueAt"]), message_id))
            self._scheduled_ids.add(message_id)
            return

        payload = dict(row.get("payload") or {})
        attempt_count = int(row.get("attemptCount", 0))
        shard_id = str(row.get("shard_id", ""))

        result = await self._sender.send(message_id, payload)
        if result.ok:
            await self._repo.mark_success(
                message_id=message_id,
                attempt_count_after=attempt_count + 1,
            )
            await self._wal.enqueue(
                {
                    "ts_ms": epoch_ms(),
                    "type": "success",
                    "messageId": message_id,
                    "shard_id": shard_id,
                    "status": "success",
                    "attemptCount": attempt_count + 1,
                },
            )
            return

        new_attempts = attempt_count + 1
        if new_attempts >= MAX_SEND_ATTEMPTS:
            await self._repo.mark_permanently_failed(
                message_id=message_id,
                attempt_count=new_attempts,
            )
            await self._wal.enqueue(
                {
                    "ts_ms": epoch_ms(),
                    "type": "failed",
                    "messageId": message_id,
                    "shard_id": shard_id,
                    "status": "failed",
                    "attemptCount": new_attempts,
                    "detail": result.detail,
                },
            )
            return

        next_due = next_retry_due_ms(epoch_ms())
        await self._repo.mark_failure_schedule_retry(
            message_id=message_id,
            new_attempt_count=new_attempts,
            next_due_at_ms=next_due,
        )
        heapq.heappush(self._heap, (next_due, message_id))
        self._scheduled_ids.add(message_id)
        await self._wal.enqueue(
            {
                "ts_ms": epoch_ms(),
                "type": "retry_scheduled",
                "messageId": message_id,
                "shard_id": shard_id,
                "status": "pending",
                "attemptCount": new_attempts,
                "nextDueAt": next_due,
                "detail": result.detail,
            },
        )

    async def tick_once(self) -> None:
        now_ms = epoch_ms()
        due_ids: list[str] = []
        seen: set[str] = set()
        while self._heap and self._heap[0][0] <= now_ms:
            _, mid = heapq.heappop(self._heap)
            self._scheduled_ids.discard(mid)
            if mid in seen:
                continue
            seen.add(mid)
            due_ids.append(mid)
        if not due_ids:
            return
        await asyncio.gather(*(self._process_one(mid) for mid in due_ids))

    async def run_forever(self) -> None:
        next_reconcile = time.monotonic()
        while True:
            loop_start = time.monotonic()
            deadline = loop_start + TICK_INTERVAL_SEC

            if loop_start >= next_reconcile:
                await self.reconcile_once()
                next_reconcile = loop_start + self._reconcile_interval_sec

            await self.tick_once()

            now = time.monotonic()
            remaining = deadline - now
            if remaining > 0:
                await asyncio.sleep(remaining)
