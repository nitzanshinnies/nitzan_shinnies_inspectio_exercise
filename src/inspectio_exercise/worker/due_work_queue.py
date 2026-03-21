"""In-memory min-heap of due pending messages (nextDueAt-first)."""

from __future__ import annotations

import asyncio
import heapq
import json
import logging
from typing import Any

from inspectio_exercise.worker.pending_record import is_valid_pending_row

logger = logging.getLogger(__name__)


class DueWorkQueue:
    """Tracks pending records, S3 keys, and a due-time heap."""

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, str]] = []
        self._lock = asyncio.Lock()
        self._seq = 0
        self.records: dict[str, dict[str, Any]] = {}
        self.pending_keys: dict[str, str] = {}

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def collect_due(self, now_ms: int) -> list[tuple[str, dict[str, Any], str]]:
        async with self._lock:
            out: list[tuple[str, dict[str, Any], str]] = []
            while self._heap and self._heap[0][0] <= now_ms:
                due_ms, _, mid = heapq.heappop(self._heap)
                rec = self.records.get(mid)
                if rec is None:
                    continue
                key = self.pending_keys.get(mid)
                if key is None:
                    continue
                if int(rec["nextDueAt"]) != due_ms:
                    continue
                out.append((mid, rec, key))
            return out

    def drop_locked(self, mid: str) -> None:
        self.records.pop(mid, None)
        self.pending_keys.pop(mid, None)

    async def ingest_if_new(self, mid: str, key: str, raw: bytes) -> None:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("skipping non-JSON pending object key=%s", key)
            return
        if not is_valid_pending_row(mid, data):
            logger.warning("skipping invalid pending record key=%s", key)
            return
        async with self._lock:
            if mid in self.records:
                return
            self.records[mid] = data
            self.pending_keys[mid] = key
            self.schedule_locked(mid, int(data["nextDueAt"]))

    def schedule_locked(self, mid: str, due_ms: int) -> None:
        """Push due time (caller must hold ``lock`` when mutating a tracked message)."""
        self._seq += 1
        heapq.heappush(self._heap, (due_ms, self._seq, mid))
