"""OutcomeNotifier retries (plans/TEST_LIST.md TC-NTF-03)."""

from __future__ import annotations

from unittest import mock

import httpx
import pytest

from inspectio_exercise.worker.outcome_notifier import OutcomeNotifier

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_publish_retries_after_transient_notification_failures() -> None:
    """TC-NTF-03: notification POST fails then succeeds; publish completes."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/v1/outcomes":
            attempts["n"] += 1
            if attempts["n"] < 3:
                return httpx.Response(503, json={"code": "busy"})
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://notification") as client:
        notifier = OutcomeNotifier(client)
        with mock.patch("asyncio.sleep", new_callable=mock.AsyncMock):
            await notifier.publish(
                message_id="mid-retry",
                outcome="success",
                recorded_at=1,
                shard_id=0,
                terminal_storage_key="state/success/2020/01/01/00/mid-retry.json",
            )
    assert attempts["n"] == 3
