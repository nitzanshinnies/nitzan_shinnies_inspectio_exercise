"""Metrics for persistence writer durability path (P12.3)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PersistenceWriterMetrics:
    events_buffered: int = 0
    events_deduped: int = 0
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
