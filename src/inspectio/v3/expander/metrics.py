"""Cheap counters for expander observability (master plan §8)."""

from __future__ import annotations


class ExpansionMetrics:
    """In-process metrics; replace with shared telemetry in production."""

    def __init__(self) -> None:
        self.expanded_units_published: int = 0
        self.send_batch_throttle_retries: int = 0
