"""Fixed-interval polling loop around an async tick."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable

from inspectio_exercise.common.performance_logging import (
    DURATION_MS_DECIMALS,
    OPERATION_WORKER_TICK,
    log_performance,
)

logger = logging.getLogger(__name__)


async def run_forever_with_tick_interval(
    tick: Callable[[], Awaitable[None]],
    interval_sec: float,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        t0 = time.perf_counter()
        try:
            await tick()
        except Exception:
            logger.exception("worker tick failed")
        elapsed = time.perf_counter() - t0
        log_performance(
            component="worker",
            duration_ms=round(elapsed * 1000.0, DURATION_MS_DECIMALS),
            operation=OPERATION_WORKER_TICK,
        )
        sleep_for = max(0.0, interval_sec - elapsed)
        if sleep_for <= 0:
            continue
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=sleep_for)
