"""Metrics for persistence writer durability path (P12.3/P12.9 WS2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class PersistenceWriterMetrics:
    started_at_ms: int = 0
    polls_total: int = 0
    polls_idle: int = 0
    events_buffered: int = 0
    events_deduped: int = 0
    events_dropped_committed_watermark: int = 0
    empty_flushes_due_to_dedupe: int = 0
    events_flushed: int = 0
    segments_written: int = 0
    checkpoint_writes: int = 0
    flush_duration_ms_last: int = 0
    flush_duration_ms_max: int = 0
    flush_retries: int = 0
    flush_failures: int = 0
    s3_errors: int = 0
    lag_to_durable_commit_ms_last: int = 0
    lag_to_durable_commit_ms_max: int = 0
    s3_put_retries: int = 0
    checkpoint_write_retries: int = 0
    ack_retries: int = 0
    shard: dict[int, PersistenceWriterShardMetrics] = field(default_factory=dict)

    def init_clock(self, *, now_ms: int) -> None:
        if self.started_at_ms <= 0:
            self.started_at_ms = now_ms

    def observe_poll(self, *, idle: bool) -> None:
        self.polls_total += 1
        if idle:
            self.polls_idle += 1

    def observe_receive_batch(self, *, shard: int, events: int, now_ms: int) -> None:
        shard_metrics = self._for_shard(shard, now_ms=now_ms)
        shard_metrics.receive_batches += 1
        shard_metrics.receive_events_total += events
        shard_metrics.receive_events_last_batch = events

    def observe_flush_batch(
        self,
        *,
        shard: int,
        events: int,
        payload_bytes: int,
        duration_ms: int,
        lag_ms: int,
        buffered_events: int,
        oldest_buffer_age_ms: int,
        now_ms: int,
    ) -> None:
        shard_metrics = self._for_shard(shard, now_ms=now_ms)
        shard_metrics.flush_batches += 1
        shard_metrics.flush_events_total += events
        shard_metrics.flush_events_last_batch = events
        shard_metrics.flush_payload_bytes_last = payload_bytes
        shard_metrics.flush_duration_ms_last = duration_ms
        shard_metrics.flush_duration_ms_max = max(
            shard_metrics.flush_duration_ms_max, duration_ms
        )
        shard_metrics.lag_to_durable_commit_ms_last = lag_ms
        shard_metrics.lag_to_durable_commit_ms_max = max(
            shard_metrics.lag_to_durable_commit_ms_max, lag_ms
        )
        shard_metrics.buffered_events = buffered_events
        shard_metrics.oldest_buffer_age_ms = oldest_buffer_age_ms

    def observe_ack_batch(
        self, *, shard: int, events: int, latency_ms: int, now_ms: int
    ) -> None:
        shard_metrics = self._for_shard(shard, now_ms=now_ms)
        shard_metrics.ack_batches += 1
        shard_metrics.ack_events_total += events
        shard_metrics.ack_events_last_batch = events
        shard_metrics.ack_latency_ms_last = latency_ms
        shard_metrics.ack_latency_ms_max = max(
            shard_metrics.ack_latency_ms_max, latency_ms
        )

    def observe_retry(self, *, shard: int, operation: str, now_ms: int) -> None:
        shard_metrics = self._for_shard(shard, now_ms=now_ms)
        if operation == "s3_put":
            self.s3_put_retries += 1
            shard_metrics.s3_put_retries += 1
            return
        if operation == "checkpoint_put":
            self.checkpoint_write_retries += 1
            shard_metrics.checkpoint_write_retries += 1
            return
        if operation == "ack":
            self.ack_retries += 1
            shard_metrics.ack_retries += 1
            return
        raise ValueError(f"unknown retry operation: {operation}")

    def observe_buffer_state(
        self,
        *,
        shard: int,
        buffered_events: int,
        oldest_buffer_age_ms: int,
        now_ms: int,
    ) -> None:
        shard_metrics = self._for_shard(shard, now_ms=now_ms)
        shard_metrics.buffered_events = buffered_events
        shard_metrics.oldest_buffer_age_ms = oldest_buffer_age_ms

    def observe_transport_oldest_age(
        self, *, shard: int, age_ms: int, now_ms: int
    ) -> None:
        shard_metrics = self._for_shard(shard, now_ms=now_ms)
        shard_metrics.transport_oldest_age_ms_last = age_ms
        shard_metrics.transport_oldest_age_ms_max = max(
            shard_metrics.transport_oldest_age_ms_max, age_ms
        )

    def snapshot(self, *, now_ms: int) -> dict[str, Any]:
        self.init_clock(now_ms=now_ms)
        elapsed_ms = max(1, now_ms - self.started_at_ms)
        idle_ratio = self.polls_idle / max(1, self.polls_total)
        total_receive_events = sum(
            shard_metrics.receive_events_total for shard_metrics in self.shard.values()
        )
        ingest_events_per_sec = total_receive_events * 1000.0 / elapsed_ms
        shard_snapshot: dict[str, Any] = {}
        for shard_id in sorted(self.shard):
            shard_metrics = self.shard[shard_id]
            shard_elapsed_ms = max(1, now_ms - shard_metrics.first_seen_at_ms)
            shard_ingest_events_per_sec = (
                shard_metrics.receive_events_total * 1000.0 / shard_elapsed_ms
            )
            item = asdict(shard_metrics)
            item["ingest_events_per_sec"] = round(shard_ingest_events_per_sec, 3)
            shard_snapshot[str(shard_id)] = item
        return {
            "polls_total": self.polls_total,
            "polls_idle": self.polls_idle,
            "queue_polling_idle_ratio": round(idle_ratio, 6),
            "ingest_events_per_sec": round(ingest_events_per_sec, 3),
            "s3_put_retries": self.s3_put_retries,
            "checkpoint_write_retries": self.checkpoint_write_retries,
            "ack_retries": self.ack_retries,
            "events_buffered": self.events_buffered,
            "events_flushed": self.events_flushed,
            "flush_failures": self.flush_failures,
            "s3_errors": self.s3_errors,
            "shards": shard_snapshot,
        }

    def _for_shard(self, shard: int, *, now_ms: int) -> PersistenceWriterShardMetrics:
        item = self.shard.get(shard)
        if item is None:
            item = PersistenceWriterShardMetrics()
            item.first_seen_at_ms = now_ms
            self.shard[shard] = item
        return item


@dataclass(slots=True)
class PersistenceWriterShardMetrics:
    first_seen_at_ms: int = 0
    receive_batches: int = 0
    receive_events_total: int = 0
    receive_events_last_batch: int = 0
    flush_batches: int = 0
    flush_events_total: int = 0
    flush_events_last_batch: int = 0
    flush_payload_bytes_last: int = 0
    flush_duration_ms_last: int = 0
    flush_duration_ms_max: int = 0
    lag_to_durable_commit_ms_last: int = 0
    lag_to_durable_commit_ms_max: int = 0
    ack_batches: int = 0
    ack_events_total: int = 0
    ack_events_last_batch: int = 0
    ack_latency_ms_last: int = 0
    ack_latency_ms_max: int = 0
    s3_put_retries: int = 0
    checkpoint_write_retries: int = 0
    ack_retries: int = 0
    transport_oldest_age_ms_last: int = 0
    transport_oldest_age_ms_max: int = 0
    buffered_events: int = 0
    oldest_buffer_age_ms: int = 0
