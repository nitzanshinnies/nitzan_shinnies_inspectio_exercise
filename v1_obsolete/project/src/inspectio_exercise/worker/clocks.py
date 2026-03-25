"""Wall clock for the worker (tests patch ``inspectio_exercise.worker.clocks.now_ms``)."""

from __future__ import annotations

import time


def now_ms() -> int:
    return int(time.time() * 1000)
