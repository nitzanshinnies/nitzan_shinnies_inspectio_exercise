"""P4: full compose path — repeat count=10 → success outcomes (opt-in)."""

from __future__ import annotations

import os
import time

import httpx
import pytest


def _enabled() -> bool:
    return os.environ.get("INSPECTIO_P4_E2E") == "1"


pytestmark = pytest.mark.skipif(
    not _enabled(),
    reason="Set INSPECTIO_P4_E2E=1; run docker compose with api, expander, worker (README P4)",
)


@pytest.mark.e2e
def test_repeat_ten_eventually_lists_ten_successes() -> None:
    base = os.environ.get("INSPECTIO_P4_E2E_BASE", "http://127.0.0.1:8000").rstrip("/")
    with httpx.Client(base_url=base, timeout=30.0) as client:
        before = client.get("/messages/success", params={"limit": 100})
        before.raise_for_status()
        n0 = len(before.json()["items"])
        body = f"p4-e2e-{time.time_ns()}"
        admit = client.post(
            "/messages/repeat", params={"count": 10}, json={"body": body}
        )
        admit.raise_for_status()
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            r = client.get("/messages/success", params={"limit": 100})
            r.raise_for_status()
            n = len(r.json()["items"])
            if n >= n0 + 10:
                return
            time.sleep(0.5)
        pytest.fail("timed out waiting for 10 new success outcomes")
