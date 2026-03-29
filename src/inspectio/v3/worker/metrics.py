"""Send worker counters (master plan §8)."""

from __future__ import annotations


class SendWorkerMetrics:
    def __init__(self) -> None:
        self.send_ok: int = 0
        self.send_fail: int = 0
