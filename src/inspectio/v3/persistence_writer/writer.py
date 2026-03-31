"""Buffered segment writer with checkpoint contract (P12.3)."""

from __future__ import annotations

import asyncio
import gzip
import json
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence

from inspectio.v3.persistence_recovery.order import sorted_for_replay
from inspectio.v3.persistence_writer.metrics import PersistenceWriterMetrics
from inspectio.v3.persistence_writer.object_store import PersistenceObjectStore
from inspectio.v3.schemas.persistence_checkpoint import PersistenceCheckpointV1
from inspectio.v3.schemas.persistence_event import PersistenceEventV1

SEGMENT_CONTENT_TYPE = "application/x-ndjson"
SEGMENT_CONTENT_ENCODING = "gzip"


class PersistenceWriterFlushError(RuntimeError):
    """Raised when writer cannot flush buffered data."""


class BufferedPersistenceWriter:
    def __init__(
        self,
        *,
        store: PersistenceObjectStore,
        clock_ms: Callable[[], int],
        flush_max_events: int,
        flush_interval_ms: int,
        dedupe_event_id_cap: int,
        write_max_attempts: int,
        backoff_base_ms: int,
        backoff_max_ms: int,
        backoff_jitter_fraction: float,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._store = store
        self._clock_ms = clock_ms
        self._flush_max_events = max(1, flush_max_events)
        self._flush_interval_ms = max(1, flush_interval_ms)
        self._dedupe_event_id_cap = max(64, dedupe_event_id_cap)
        self._write_max_attempts = max(1, write_max_attempts)
        self._backoff_base_ms = max(1, backoff_base_ms)
        self._backoff_max_ms = max(self._backoff_base_ms, backoff_max_ms)
        self._backoff_jitter_fraction = max(0.0, min(backoff_jitter_fraction, 1.0))
        self._sleeper = sleeper or asyncio.sleep
        self._rng = rng or random.Random()

        self.metrics = PersistenceWriterMetrics()
        self.metrics.init_clock(now_ms=self._clock_ms())
        self._buffers: dict[int, list[PersistenceEventV1]] = {}
        self._buffer_started_at_ms: dict[int, int] = {}
        self._next_segment_seq: dict[int, int] = {}
        self._committed_watermark: dict[int, tuple[int, int]] = {}
        self._initialized_shards: set[int] = set()
        self._seen_event_ids: dict[int, set[str]] = {}
        self._seen_event_queue: dict[int, deque[str]] = {}

    async def ingest_events(self, events: Sequence[PersistenceEventV1]) -> None:
        for event in events:
            await self._ensure_shard_initialized(event.shard)
            if self._is_duplicate(event):
                self.metrics.events_deduped += 1
                continue
            shard_buf = self._buffers.setdefault(event.shard, [])
            if not shard_buf:
                self._buffer_started_at_ms[event.shard] = self._clock_ms()
            shard_buf.append(event)
            self.metrics.events_buffered += 1

    async def flush_due(self, *, force: bool = False) -> list[PersistenceEventV1]:
        now = self._clock_ms()
        flushed: list[PersistenceEventV1] = []
        for shard, events in list(self._buffers.items()):
            if not events:
                continue
            buffered_for = now - self._buffer_started_at_ms.get(shard, now)
            self.metrics.observe_buffer_state(
                shard=shard,
                buffered_events=len(events),
                oldest_buffer_age_ms=max(0, buffered_for),
                now_ms=now,
            )
            should_flush = (
                force
                or len(events) >= self._flush_max_events
                or buffered_for >= self._flush_interval_ms
            )
            if should_flush:
                flushed.extend(await self._flush_shard(shard, events))
        return flushed

    async def _flush_shard(
        self,
        shard: int,
        events: list[PersistenceEventV1],
    ) -> list[PersistenceEventV1]:
        flush_started = time.perf_counter()
        ordered = sorted_for_replay(events)
        oldest_buffer_age_ms = max(
            0,
            self._clock_ms() - self._buffer_started_at_ms.get(shard, self._clock_ms()),
        )
        watermark = self._committed_watermark.get(shard, (-1, -1))
        filtered = [e for e in ordered if self._ordering_key(e) > watermark]
        dropped = len(ordered) - len(filtered)
        if dropped:
            self.metrics.events_dropped_committed_watermark += dropped
        if not filtered:
            self.metrics.empty_flushes_due_to_dedupe += 1
            self._buffers[shard] = []
            self._buffer_started_at_ms.pop(shard, None)
            self.metrics.observe_buffer_state(
                shard=shard,
                buffered_events=0,
                oldest_buffer_age_ms=0,
                now_ms=self._clock_ms(),
            )
            # Return all input events for ack (already committed).
            return ordered

        segment_seq = self._next_segment_seq[shard]
        object_key = self._segment_key(shard=shard, seq=segment_seq)
        checkpoint_key = self._checkpoint_key(shard)

        payload = self._encode_segment(filtered)
        last_event_index = filtered[-1].segment_event_index if filtered else 0
        max_source_segment, max_source_index = self._max_ordering_key(filtered)

        for attempt in range(self._write_max_attempts):
            current_operation = "s3_put"
            try:
                # Contract: segment object must be durable before checkpoint advance.
                await self._store.put_bytes(
                    key=object_key,
                    data=payload,
                    content_type=SEGMENT_CONTENT_TYPE,
                    content_encoding=SEGMENT_CONTENT_ENCODING,
                )
                checkpoint = PersistenceCheckpointV1(
                    shard=shard,
                    last_segment_seq=segment_seq,
                    next_segment_seq=segment_seq + 1,
                    last_event_index=last_event_index,
                    committed_source_segment_seq=max_source_segment,
                    committed_source_event_index=max_source_index,
                    updated_at_ms=self._clock_ms(),
                    segment_object_key=object_key,
                )
                current_operation = "checkpoint_put"
                await self._store.put_json(
                    key=checkpoint_key,
                    data=checkpoint.model_dump(mode="json", by_alias=True),
                )
                self.metrics.events_flushed += len(filtered)
                self.metrics.segments_written += 1
                self.metrics.checkpoint_writes += 1
                dur_ms = int((time.perf_counter() - flush_started) * 1000)
                self.metrics.flush_duration_ms_last = dur_ms
                self.metrics.flush_duration_ms_max = max(
                    self.metrics.flush_duration_ms_max,
                    dur_ms,
                )
                lag = max(0, self._clock_ms() - max(e.emitted_at_ms for e in filtered))
                self.metrics.lag_to_durable_commit_ms_last = lag
                self.metrics.lag_to_durable_commit_ms_max = max(
                    self.metrics.lag_to_durable_commit_ms_max,
                    lag,
                )
                self._next_segment_seq[shard] = segment_seq + 1
                self._committed_watermark[shard] = (
                    max_source_segment,
                    max_source_index,
                )
                self._buffers[shard] = []
                self._buffer_started_at_ms.pop(shard, None)
                self.metrics.observe_flush_batch(
                    shard=shard,
                    events=len(filtered),
                    payload_bytes=len(payload),
                    duration_ms=dur_ms,
                    lag_ms=lag,
                    buffered_events=0,
                    oldest_buffer_age_ms=oldest_buffer_age_ms,
                    now_ms=self._clock_ms(),
                )
                # Ack all input events: committed+already-committed.
                return ordered
            except Exception as exc:  # noqa: BLE001
                self.metrics.s3_errors += len(filtered)
                if attempt + 1 >= self._write_max_attempts:
                    self.metrics.flush_failures += len(filtered)
                    raise PersistenceWriterFlushError(str(exc)) from exc
                self.metrics.flush_retries += len(filtered)
                self.metrics.observe_retry(
                    shard=shard,
                    operation=current_operation,
                    now_ms=self._clock_ms(),
                )
                delay_ms = self._compute_backoff_ms(attempt)
                await self._sleeper(delay_ms / 1000.0)
        return []

    async def _ensure_shard_initialized(self, shard: int) -> None:
        if shard in self._initialized_shards:
            return
        cp = await self._store.get_json(key=self._checkpoint_key(shard))
        if cp is None:
            self._next_segment_seq[shard] = 0
            self._committed_watermark[shard] = (-1, -1)
        else:
            parsed = PersistenceCheckpointV1.model_validate(cp)
            self._next_segment_seq[shard] = parsed.next_segment_seq
            self._committed_watermark[shard] = (
                parsed.committed_source_segment_seq,
                parsed.committed_source_event_index,
            )
        self._initialized_shards.add(shard)
        self._buffers.setdefault(shard, [])
        self._seen_event_ids.setdefault(shard, set())
        self._seen_event_queue.setdefault(shard, deque())

    def _is_duplicate(self, event: PersistenceEventV1) -> bool:
        seen = self._seen_event_ids.setdefault(event.shard, set())
        queue = self._seen_event_queue.setdefault(event.shard, deque())
        if event.event_id in seen:
            return True
        seen.add(event.event_id)
        queue.append(event.event_id)
        while len(queue) > self._dedupe_event_id_cap:
            old = queue.popleft()
            seen.discard(old)
        return False

    @staticmethod
    def _segment_key(*, shard: int, seq: int) -> str:
        return f"state/events/{shard}/{seq:020d}.ndjson.gz"

    @staticmethod
    def _checkpoint_key(shard: int) -> str:
        return f"state/checkpoints/{shard}/latest.json"

    @staticmethod
    def _encode_segment(events: list[PersistenceEventV1]) -> bytes:
        lines = [
            json.dumps(e.model_dump(mode="json", by_alias=True, exclude_none=True))
            for e in events
        ]
        ndjson = ("\n".join(lines) + "\n").encode("utf-8")
        return gzip.compress(ndjson)

    @staticmethod
    def _ordering_key(event: PersistenceEventV1) -> tuple[int, int]:
        return (event.segment_seq, event.segment_event_index)

    @classmethod
    def _max_ordering_key(
        cls,
        events: list[PersistenceEventV1],
    ) -> tuple[int, int]:
        if not events:
            return (-1, -1)
        return max(cls._ordering_key(e) for e in events)

    def _compute_backoff_ms(self, attempt_zero_indexed: int) -> int:
        expo = self._backoff_base_ms * (2**attempt_zero_indexed)
        capped = min(self._backoff_max_ms, expo)
        jitter = int(self._rng.random() * capped * self._backoff_jitter_fraction)
        return min(self._backoff_max_ms, capped + jitter)
