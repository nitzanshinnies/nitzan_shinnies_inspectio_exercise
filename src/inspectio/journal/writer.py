"""S3 gzip journal segments with §29.8 flush policy."""

from __future__ import annotations

import asyncio
import gzip
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from inspectio.journal.records import (
    JournalRecordType,
    JournalRecordV1,
    encode_line,
)
from inspectio.journal.replay import load_max_record_index_for_shard
from inspectio.settings import Settings

log = logging.getLogger("inspectio.journal.writer")

S3_RETRY_MAX_ATTEMPTS = 8
S3_RETRY_BASE_DELAY_SEC = 0.05
S3_RETRY_MAX_DELAY_SEC = 2.0


def _utc_parts(now_ms: int) -> tuple[str, str, str, str]:
    dt = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
    return (dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d"), dt.strftime("%H"))


class JournalWriter:
    """Buffered NDJSON gzip segments per shard; monotonic `recordIndex` per shard."""

    def __init__(
        self,
        settings: Settings,
        *,
        initial_hwm: dict[int, int] | None = None,
    ) -> None:
        self._settings = settings
        self._bucket = settings.s3_bucket.strip()
        self._hwm: dict[int, int] = dict(initial_hwm or {})
        self._last_assigned: dict[int, int] = {}
        self._buffers: dict[int, list[str]] = defaultdict(list)
        self._last_flush_mono: dict[int, float] = {}
        self._segment_seq: dict[tuple[int, str, str, str, str], int] = {}
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._session = aioboto3.Session()

    def _client_kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {"region_name": self._settings.aws_region}
        if self._settings.aws_endpoint_url:
            kw["endpoint_url"] = self._settings.aws_endpoint_url
        return kw

    async def _put_object_with_retry(self, key: str, body: bytes) -> None:
        delay = S3_RETRY_BASE_DELAY_SEC
        async with self._session.client("s3", **self._client_kwargs()) as s3:
            for attempt in range(S3_RETRY_MAX_ATTEMPTS):
                try:
                    await s3.put_object(Bucket=self._bucket, Key=key, Body=body)
                    return
                except ClientError as exc:
                    code = exc.response.get("Error", {}).get("Code", "")
                    if code not in (
                        "Throttling",
                        "SlowDown",
                        "ServiceUnavailable",
                        "InternalError",
                    ):
                        raise
                    if attempt == S3_RETRY_MAX_ATTEMPTS - 1:
                        raise
                    log.warning(
                        "s3_put_retry key=%s code=%s attempt=%s", key, code, attempt
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, S3_RETRY_MAX_DELAY_SEC)

    def _next_record_index_locked(self, shard_id: int) -> int:
        start = max(self._hwm.get(shard_id, -1), self._last_assigned.get(shard_id, -1))
        nxt = start + 1
        self._last_assigned[shard_id] = nxt
        return nxt

    async def build_record(
        self,
        shard_id: int,
        *,
        record_type: JournalRecordType,
        message_id: str,
        ts_ms: int,
        payload: dict[str, Any],
    ) -> JournalRecordV1:
        async with self._locks[shard_id]:
            idx = self._next_record_index_locked(shard_id)
        return JournalRecordV1(
            v=1,
            type=record_type,
            shard_id=shard_id,
            message_id=message_id,
            ts_ms=ts_ms,
            record_index=idx,
            payload=payload,
        )

    async def append_encoded_line(self, shard_id: int, line: str) -> None:
        async with self._locks[shard_id]:
            self._buffers[shard_id].append(line)
            if shard_id not in self._last_flush_mono:
                self._last_flush_mono[shard_id] = time.monotonic()
            await self._maybe_flush_locked(shard_id)

    async def append_record(self, record: JournalRecordV1) -> None:
        line = encode_line(record)
        await self.append_encoded_line(record.shard_id, line)

    async def _maybe_flush_locked(self, shard_id: int) -> None:
        lines = self._buffers[shard_id]
        if not lines:
            return
        now_m = time.monotonic()
        interval = self._settings.journal_flush_interval_ms / 1000.0
        due_time = (now_m - self._last_flush_mono[shard_id]) >= interval
        due_size = len(lines) >= self._settings.journal_flush_max_lines
        if not (due_time or due_size):
            return
        await self._flush_shard_body(shard_id, lines)
        self._buffers[shard_id] = []
        self._last_flush_mono[shard_id] = time.monotonic()

    async def _flush_shard_body(self, shard_id: int, lines: list[str]) -> None:
        if not self._bucket:
            msg = "INSPECTIO_S3_BUCKET must be set for journal writes"
            raise RuntimeError(msg)
        now_ms = int(time.time() * 1000)
        y, m, d, h = _utc_parts(now_ms)
        bucket = (shard_id, y, m, d, h)
        seq = self._segment_seq.get(bucket, 0) + 1
        self._segment_seq[bucket] = seq
        key = f"state/journal/{shard_id:05d}/{y}/{m}/{d}/{h}/{now_ms}-{seq}.ndjson.gz"
        raw = "\n".join(lines) + "\n"
        blob = gzip.compress(raw.encode("utf-8"))
        await self._put_object_with_retry(key, blob)

    async def flush_shard(self, shard_id: int) -> None:
        async with self._locks[shard_id]:
            lines = self._buffers[shard_id]
            if not lines:
                return
            await self._flush_shard_body(shard_id, lines)
            self._buffers[shard_id] = []
            self._last_flush_mono[shard_id] = time.monotonic()

    async def flush_all(self) -> None:
        for sid in list(self._buffers.keys()):
            await self.flush_shard(sid)

    def get_last_record_index(self, shard_id: int) -> int:
        """High-water `recordIndex` for `shard_id` (including buffered but assigned)."""
        return max(
            self._hwm.get(shard_id, -1),
            self._last_assigned.get(shard_id, -1),
        )

    async def periodic_flush_loop(self, stop: asyncio.Event) -> None:
        interval = max(self._settings.journal_flush_interval_ms / 1000.0 / 2, 0.02)
        while not stop.is_set():
            await asyncio.sleep(interval)
            for sid in list(self._buffers.keys()):
                async with self._locks[sid]:
                    lines = self._buffers[sid]
                    if not lines:
                        continue
                    now_m = time.monotonic()
                    if (
                        now_m - self._last_flush_mono.get(sid, now_m)
                        >= self._settings.journal_flush_interval_ms / 1000.0
                    ):
                        await self._flush_shard_body(sid, lines)
                        self._buffers[sid] = []
                        self._last_flush_mono[sid] = time.monotonic()


async def bootstrap_hwm_for_shards(
    settings: Settings,
    shard_ids: list[int],
) -> dict[int, int]:
    """Load max `recordIndex` per shard from S3 (empty bucket -> -1)."""
    bucket = settings.s3_bucket.strip()
    if not bucket:
        return {s: -1 for s in shard_ids}
    session = aioboto3.Session()
    kwargs = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    out: dict[int, int] = {}

    async with session.client("s3", **kwargs) as s3:
        for sid in shard_ids:
            out[sid] = await load_max_record_index_for_shard(s3, bucket, sid)
    return out


def snapshot_body(shard_id: int, last_record_index: int, pending: list[dict]) -> bytes:
    """Serialize snapshot JSON for `state/snapshot/<shard>/latest.json`."""
    import json

    payload = {
        "v": 1,
        "shardId": shard_id,
        "lastRecordIndex": last_record_index,
        "pending": pending,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


async def write_snapshot(
    settings: Settings,
    shard_id: int,
    last_record_index: int,
    pending: list[dict],
) -> None:
    """Best-effort snapshot write (§18.4)."""
    bucket = settings.s3_bucket.strip()
    if not bucket:
        return
    key = f"state/snapshot/{shard_id:05d}/latest.json"
    body = snapshot_body(shard_id, last_record_index, pending)
    session = aioboto3.Session()
    kwargs = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        kwargs["endpoint_url"] = settings.aws_endpoint_url
    async with session.client("s3", **kwargs) as s3:
        delay = S3_RETRY_BASE_DELAY_SEC
        for attempt in range(S3_RETRY_MAX_ATTEMPTS):
            try:
                await s3.put_object(Bucket=bucket, Key=key, Body=body)
                return
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in (
                    "Throttling",
                    "SlowDown",
                    "ServiceUnavailable",
                ):
                    raise
                await asyncio.sleep(delay)
                delay = min(delay * 2, S3_RETRY_MAX_DELAY_SEC)


def run_snapshot_periodically(
    interval_sec: float,
    factory: Callable[[], Awaitable[None]],
) -> asyncio.Task:
    """Background snapshot ticker."""

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval_sec)
            await factory()

    return asyncio.create_task(_loop())
