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


async def _wait_interval_or_stop_or_wake(
    stop: asyncio.Event,
    sleep_for: float,
    wake: asyncio.Event | None,
) -> None:
    """Wait until ``sleep_for`` elapses, ``stop`` is set, or ``wake`` fires (``sleep_for`` > 0)."""
    tasks: list[asyncio.Task[object]] = [
        asyncio.create_task(asyncio.sleep(sleep_for)),
        asyncio.create_task(stop.wait()),
    ]
    if wake is not None:
        tasks.append(asyncio.create_task(wake.wait()))
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
    if wake is not None and wake.is_set():
        wake.clear()


async def run_forever_with_tick_interval(
    tick: Callable[[], Awaitable[None]],
    interval_sec: float,
    stop: asyncio.Event,
    wake: asyncio.Event | None = None,
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
        if wake is not None and wake.is_set():
            wake.clear()
            continue
        if sleep_for <= 0:
            continue
        await _wait_interval_or_stop_or_wake(stop, sleep_for, wake)
