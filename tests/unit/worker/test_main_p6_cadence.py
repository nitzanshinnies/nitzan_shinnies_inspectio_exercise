"""P6 worker main cadence tests."""

from __future__ import annotations

import asyncio

import pytest

from inspectio.worker.main import run_consumer_loop


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_consumer_loop_sleeps_for_remaining_cadence() -> None:
    consume_calls = 0
    wakeup_calls = 0
    sleeps: list[float] = []

    async def _consume_once() -> int:
        nonlocal consume_calls
        consume_calls += 1
        if consume_calls >= 2:
            raise asyncio.CancelledError
        return 0

    async def _wakeup_once() -> int:
        nonlocal wakeup_calls
        wakeup_calls += 1
        return 0

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    with pytest.raises(asyncio.CancelledError):
        await run_consumer_loop(
            consume_once=_consume_once,
            wakeup_once=_wakeup_once,
            poll_interval_sec=0.5,
            sleep_func=_sleep,
        )

    assert consume_calls >= 2
    assert wakeup_calls >= 1
    assert sleeps
    assert all(s >= 0 for s in sleeps)
