"""In-process counters for persistence producer health (P12.2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PersistenceTransportMetrics:
    published_ok: int = 0
    publish_retries: int = 0
    publish_failures: int = 0
    dropped_backpressure: int = 0
    dlq_published_ok: int = 0
    dlq_failures: int = 0
    publish_duration_ms_last: int = 0
    publish_duration_ms_max: int = 0
    publish_duration_ms_total: int = 0
    publish_success_batches: int = 0

    def observe_publish_duration(self, *, duration_ms: int) -> None:
        safe = max(0, duration_ms)
        self.publish_success_batches += 1
        self.publish_duration_ms_last = safe
        self.publish_duration_ms_max = max(self.publish_duration_ms_max, safe)
        self.publish_duration_ms_total += safe
