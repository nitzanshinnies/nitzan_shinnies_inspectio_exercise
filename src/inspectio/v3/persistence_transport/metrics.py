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
