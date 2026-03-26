"""S3 journal writer with flush policy and retry/backoff (§5.1, §29.8)."""

from __future__ import annotations

import asyncio
import datetime as dt
import gzip
from typing import Any, Awaitable, Callable, Protocol

from inspectio.journal.records import (
    JournalRecordV1,
    encode_line,
    validate_monotonic_record_index,
)

DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SEC = 0.05
INITIAL_SEGMENT_SEQUENCE = 0


class S3PutObjectClient(Protocol):
    """Minimal async S3 client protocol needed by journal writer."""

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        """Persist one S3 object."""


class JournalWriter:
    """Single-writer-per-shard buffered S3 segment writer."""

    def __init__(
        self,
        *,
        s3_client: S3PutObjectClient,
        bucket: str,
        flush_interval_ms: int,
        flush_max_lines: int,
        max_retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
        retry_backoff_sec: float = DEFAULT_RETRY_BACKOFF_SEC,
        sleep_func: Callable[[float], Awaitable[None]] | None = None,
        on_s3_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._s3_client = s3_client
        self._bucket = bucket
        self._flush_interval_ms = flush_interval_ms
        self._flush_max_lines = flush_max_lines
        self._max_retry_attempts = max_retry_attempts
        self._retry_backoff_sec = retry_backoff_sec
        self._sleep = sleep_func or asyncio.sleep
        self._on_s3_error = on_s3_error

        self._pending_lines: list[str] = []
        self._pending_segment_start_ms: int | None = None
        self._segment_sequence = INITIAL_SEGMENT_SEQUENCE
        self._shard_id: int | None = None
        self._last_record_index: int | None = None
        self._last_flush_ms: int | None = None
        self._s3_errors_total = 0

    @property
    def s3_errors_total(self) -> int:
        """Number of S3 write errors observed by this writer instance."""
        return self._s3_errors_total

    async def append(self, record: JournalRecordV1) -> None:
        """Append one record and flush if max-lines threshold is reached."""
        self._init_shard_if_needed(record.shard_id)
        validate_monotonic_record_index(self._last_record_index, record)
        self._last_record_index = record.record_index

        if self._pending_segment_start_ms is None:
            self._pending_segment_start_ms = record.ts_ms
        self._pending_lines.append(encode_line(record))
        if len(self._pending_lines) >= self._flush_max_lines:
            await self.flush(force=True)

    async def flush_if_due(self, now_ms: int) -> None:
        """Flush buffered lines when elapsed interval threshold is reached."""
        if not self._pending_lines:
            return
        if self._last_flush_ms is None:
            elapsed_ms = now_ms - (self._pending_segment_start_ms or now_ms)
        else:
            elapsed_ms = now_ms - self._last_flush_ms
        if elapsed_ms >= self._flush_interval_ms:
            await self.flush(force=True)

    async def flush(self, *, force: bool = False) -> None:
        """Flush pending lines to a new gzip NDJSON segment."""
        if not self._pending_lines:
            return
        if not force and len(self._pending_lines) < self._flush_max_lines:
            return
        await self._write_segment_with_retry()
        self._pending_lines.clear()
        self._pending_segment_start_ms = None

    def _init_shard_if_needed(self, shard_id: int) -> None:
        if self._shard_id is None:
            self._shard_id = shard_id
            return
        if shard_id != self._shard_id:
            raise ValueError("JournalWriter instance must write one shard only")

    async def _write_segment_with_retry(self) -> None:
        self._segment_sequence += 1
        key = self._build_s3_key()
        body = self._build_segment_body()
        attempt = 0
        while True:
            try:
                await self._s3_client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=body,
                    ContentType="application/x-ndjson",
                    ContentEncoding="gzip",
                )
                self._last_flush_ms = self._segment_start_ms_required()
                return
            except Exception as exc:  # pragma: no cover - defensive branch
                self._s3_errors_total += 1
                if self._on_s3_error is not None:
                    self._on_s3_error(exc)
                if not _is_retryable_s3_throttling(exc):
                    raise
                attempt += 1
                if attempt > self._max_retry_attempts:
                    raise
                delay = self._retry_backoff_sec * (2 ** (attempt - 1))
                await self._sleep(delay)

    def _segment_start_ms_required(self) -> int:
        if self._pending_segment_start_ms is None:
            raise RuntimeError("missing segment start for pending lines")
        return self._pending_segment_start_ms

    def _build_segment_body(self) -> bytes:
        text = "\n".join(self._pending_lines) + "\n"
        return gzip.compress(text.encode("utf-8"))

    def _build_s3_key(self) -> str:
        shard_id = self._shard_required()
        segment_start_ms = self._segment_start_ms_required()
        stamp = dt.datetime.fromtimestamp(segment_start_ms / 1000, tz=dt.timezone.utc)
        return (
            f"state/journal/{shard_id}/{stamp:%Y/%m/%d/%H}/"
            f"{segment_start_ms}-{self._segment_sequence:06d}.ndjson.gz"
        )

    def _shard_required(self) -> int:
        if self._shard_id is None:
            raise RuntimeError("missing shard id")
        return self._shard_id


def _is_retryable_s3_throttling(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_markers = ("slowdown", "throttl", "503", "serviceunavailable")
    return any(marker in message for marker in retryable_markers)
