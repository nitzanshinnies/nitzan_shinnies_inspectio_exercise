"""Bounded persistence retries (plans/RESILIENCE.md §5)."""

from __future__ import annotations

import httpx
import pytest

from inspectio_exercise.worker.persistence_retry import (
    is_transient_persistence_failure,
    run_with_persistence_retries,
)

pytestmark = pytest.mark.unit


def test_is_transient_persistence_failure_http_status() -> None:
    req = httpx.Request("GET", "http://example.invalid")
    exc_503 = httpx.HTTPStatusError(
        "s",
        request=req,
        response=httpx.Response(503, request=req),
    )
    assert is_transient_persistence_failure(exc_503)
    exc_429 = httpx.HTTPStatusError(
        "s",
        request=req,
        response=httpx.Response(429, request=req),
    )
    assert is_transient_persistence_failure(exc_429)
    exc_404 = httpx.HTTPStatusError(
        "s",
        request=req,
        response=httpx.Response(404, request=req),
    )
    assert not is_transient_persistence_failure(exc_404)


@pytest.mark.asyncio
async def test_run_with_persistence_retries_eventually_succeeds() -> None:
    attempts = 0

    async def factory() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            req = httpx.Request("GET", "http://example.invalid")
            raise httpx.HTTPStatusError(
                "s",
                request=req,
                response=httpx.Response(503, request=req),
            )
        return "ok"

    out = await run_with_persistence_retries(
        "probe",
        factory,
        max_attempts=5,
        base_delay_sec=0.001,
    )
    assert out == "ok"
    assert attempts == 3
