"""Asynchronous S3 WAL: buffer state events, flush JSON Lines once per interval.

Layout: ``s3://<bucket>/<wal_prefix>/<writer_id>/<unix_ms>.jsonl`` (append-only PUT per flush).
Flusher uses ``time.monotonic()`` pacing so a ~1s cadence does not drift under load.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from inspectio.v3.iter4_dynamo_wal.constants import WAL_FLUSH_INTERVAL_SEC


def _wal_object_key(*, prefix: str, writer_id: str, ts_ms: int) -> str:
    p = prefix.strip("/")
    wid = writer_id.strip("/")
    return f"{p}/{wid}/{ts_ms}.jsonl"


class WalBuffer:
    def __init__(
        self,
        *,
        writer_id: str,
        bucket: str,
        wal_prefix: str,
        flush_interval_sec: float = WAL_FLUSH_INTERVAL_SEC,
    ) -> None:
        self._writer_id = writer_id
        self._bucket = bucket
        self._wal_prefix = wal_prefix
        self._interval = flush_interval_sec
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._s3_client: Any = None

    def attach_s3_client(self, client: Any) -> None:
        self._s3_client = client

    async def enqueue(self, event: dict[str, Any]) -> None:
        await self._queue.put(event)

    async def _flush_once(self) -> None:
        batch: list[dict[str, Any]] = []
        while True:
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not batch or self._s3_client is None:
            return
        body = "\n".join(json.dumps(evt, separators=(",", ":")) for evt in batch) + "\n"
        ts_ms = int(time.time() * 1000)
        key = _wal_object_key(
            prefix=self._wal_prefix,
            writer_id=self._writer_id,
            ts_ms=ts_ms,
        )
        await self._s3_client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/x-ndjson",
        )

    async def _run(self) -> None:
        while not self._stop.is_set():
            loop_start = time.monotonic()
            deadline = loop_start + self._interval
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._interval,
                )
            except TimeoutError:
                pass
            if self._stop.is_set():
                break
            await self._flush_once()
            remainder = deadline - time.monotonic()
            if remainder > 0 and not self._stop.is_set():
                await asyncio.sleep(remainder)
        await self._flush_once()

    def start_background(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="wal-flusher")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
