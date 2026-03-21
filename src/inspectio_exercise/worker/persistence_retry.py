"""Bounded backoff for transient persistence HTTP failures (plans/RESILIENCE.md §5)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

logger = logging.getLogger(__name__)

T = TypeVar("T")


def is_transient_persistence_failure(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, (httpx.RequestError, OSError))


async def run_with_persistence_retries(
    op_name: str,
    factory: Callable[[], Awaitable[T]],
    *,
    base_delay_sec: float,
    max_attempts: int,
) -> T:
    last: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return await factory()
        except BaseException as exc:
            last = exc
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if not is_transient_persistence_failure(exc):
                raise
            if attempt + 1 >= max_attempts:
                raise
            delay = base_delay_sec * (2**attempt)
            logger.warning(
                "persistence %s transient failure attempt %s/%s, retry in %.3fs",
                op_name,
                attempt + 1,
                max_attempts,
                delay,
                exc_info=exc,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable") from last
