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
    checkpoint_writes_skipped_due_to_cadence: int = 0
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
    flushes_since_last_checkpoint: int = 0
    flush_trigger_forced_total: int = 0
    flush_trigger_occupancy_total: int = 0
    flush_trigger_interval_total: int = 0
    ack_queue_depth_current: int = 0
    ack_queue_depth_high_water_mark: int = 0
    ack_queue_blocked_push_total: int = 0
    flush_loop_iterations_total: int = 0
    flush_loop_noop_total: int = 0
    receive_loop_iterations_total: int = 0
    pipeline_mode: str = "legacy"
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
        shard_metrics.flush_duration_ms_total += duration_ms
        shard_metrics.flush_duration_ms_max = max(
            shard_metrics.flush_duration_ms_max, duration_ms
        )
        shard_metrics.lag_to_durable_commit_ms_last = lag_ms
        shard_metrics.lag_to_durable_commit_ms_max = max(
            shard_metrics.lag_to_durable_commit_ms_max, lag_ms
        )
        shard_metrics.buffered_events = buffered_events
        shard_metrics.oldest_buffer_age_ms = oldest_buffer_age_ms

    def observe_flush_trigger(self, *, shard: int, trigger: str, now_ms: int) -> None:
        shard_metrics = self._for_shard(shard, now_ms=now_ms)
        if trigger == "force":
            self.flush_trigger_forced_total += 1
            shard_metrics.flush_trigger_forced += 1
            return
        if trigger == "occupancy":
            self.flush_trigger_occupancy_total += 1
            shard_metrics.flush_trigger_occupancy += 1
            return
        if trigger == "interval":
            self.flush_trigger_interval_total += 1
            shard_metrics.flush_trigger_interval += 1
            return
        raise ValueError(f"unknown flush trigger: {trigger}")

    def observe_ack_queue_depth(self, *, depth: int) -> None:
        safe_depth = max(0, depth)
        self.ack_queue_depth_current = safe_depth
        self.ack_queue_depth_high_water_mark = max(
            self.ack_queue_depth_high_water_mark,
            safe_depth,
        )

    def observe_ack_queue_blocked_push(self) -> None:
        self.ack_queue_blocked_push_total += 1

    def observe_flush_loop_iteration(self, *, noop: bool) -> None:
        self.flush_loop_iterations_total += 1
        if noop:
            self.flush_loop_noop_total += 1

    def observe_receive_loop_iteration(self) -> None:
        self.receive_loop_iterations_total += 1

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

    def observe_checkpoint_write(self, *, shard: int, now_ms: int) -> None:
        shard_metrics = self._for_shard(shard, now_ms=now_ms)
        shard_metrics.flushes_since_last_checkpoint = 0

    def observe_checkpoint_skip(self, *, shard: int, now_ms: int) -> None:
        self.checkpoint_writes_skipped_due_to_cadence += 1
        shard_metrics = self._for_shard(shard, now_ms=now_ms)
        shard_metrics.flushes_since_last_checkpoint += 1

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
        shard_metrics.buffered_events_high_water_mark = max(
            shard_metrics.buffered_events_high_water_mark,
            buffered_events,
        )

    def observe_transport_oldest_age(
        self, *, shard: int, age_ms: int, sampled_at_ms: int, now_ms: int
    ) -> None:
        shard_metrics = self._for_shard(shard, now_ms=now_ms)
        shard_metrics.transport_oldest_age_ms_last = age_ms
        shard_metrics.transport_oldest_age_ms_max = max(
            shard_metrics.transport_oldest_age_ms_max, age_ms
        )
        shard_metrics.transport_oldest_age_sampled_at_ms = sampled_at_ms

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
            item["flushes_per_sec"] = round(
                shard_metrics.flush_batches * 1000.0 / shard_elapsed_ms,
                3,
            )
            item["avg_events_per_flush"] = round(
                shard_metrics.flush_events_total / max(1, shard_metrics.flush_batches),
                3,
            )
            item["interval_triggered_flush_ratio"] = round(
                shard_metrics.flush_trigger_interval
                / max(1, shard_metrics.flush_batches),
                6,
            )
            item["avg_flush_latency_ms"] = round(
                shard_metrics.flush_duration_ms_total
                / max(1, shard_metrics.flush_batches),
                3,
            )
            shard_snapshot[str(shard_id)] = item
        return {
            "snapshot_emitted_at_ms": now_ms,
            "polls_total": self.polls_total,
            "polls_idle": self.polls_idle,
            "queue_polling_idle_ratio": round(idle_ratio, 6),
            "ingest_events_per_sec": round(ingest_events_per_sec, 3),
            "s3_put_retries": self.s3_put_retries,
            "checkpoint_write_retries": self.checkpoint_write_retries,
            "checkpoint_writes_skipped_due_to_cadence": self.checkpoint_writes_skipped_due_to_cadence,
            "ack_retries": self.ack_retries,
            "flush_trigger_forced_total": self.flush_trigger_forced_total,
            "flush_trigger_interval_total": self.flush_trigger_interval_total,
            "flush_trigger_occupancy_total": self.flush_trigger_occupancy_total,
            "ack_queue_depth_current": self.ack_queue_depth_current,
            "ack_queue_depth_high_water_mark": self.ack_queue_depth_high_water_mark,
            "ack_queue_blocked_push_total": self.ack_queue_blocked_push_total,
            "flush_loop_iterations_total": self.flush_loop_iterations_total,
            "flush_loop_noop_total": self.flush_loop_noop_total,
            "receive_loop_iterations_total": self.receive_loop_iterations_total,
            "pipeline_mode": self.pipeline_mode,
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
    flush_duration_ms_total: int = 0
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
    flush_trigger_forced: int = 0
    flush_trigger_interval: int = 0
    flush_trigger_occupancy: int = 0
    flushes_since_last_checkpoint: int = 0
    transport_oldest_age_ms_last: int = 0
    transport_oldest_age_ms_max: int = 0
    transport_oldest_age_sampled_at_ms: int = 0
    buffered_events: int = 0
    oldest_buffer_age_ms: int = 0
    buffered_events_high_water_mark: int = 0
