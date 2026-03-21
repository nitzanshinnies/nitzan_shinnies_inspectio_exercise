"""Fixed-interval polling loop around an async tick."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


async def run_forever_with_tick_interval(
    tick: Callable[[], Awaitable[None]],
    interval_sec: float,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        t0 = time.monotonic()
        try:
            await tick()
        except Exception:
            logger.exception("worker tick failed")
        elapsed = time.monotonic() - t0
        sleep_for = max(0.0, interval_sec - elapsed)
        if sleep_for <= 0:
            continue
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=sleep_for)
