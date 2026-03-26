"""P7 API GET outcomes proxy tests (TC-API-006/007)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from inspectio.api.app import create_app


class _FakeNotificationClient:
    def __init__(self) -> None:
        self.last_success_limit: int | None = None
        self.last_failed_limit: int | None = None

    async def get_success(self, *, limit: int) -> dict:
        self.last_success_limit = limit
        return {
            "items": [
                {
                    "messageId": "m-2",
                    "attemptCount": 2,
                    "finalTimestamp": 2000,
                    "reason": None,
                },
                {
                    "messageId": "m-1",
                    "attemptCount": 1,
                    "finalTimestamp": 1000,
                    "reason": None,
                },
            ][:limit]
        }

    async def get_failed(self, *, limit: int) -> dict:
        self.last_failed_limit = limit
        return {
            "items": [
                {
                    "messageId": "m-f",
                    "attemptCount": 6,
                    "finalTimestamp": 3000,
                    "reason": "send_failed",
                }
            ][:limit]
        }


@pytest.mark.unit
def test_tc_api_006_get_success_proxy_returns_limited_items() -> None:
    app = create_app()
    fake = _FakeNotificationClient()
    app.state.notification_client = fake
    client = TestClient(app)

    resp = client.get("/messages/success?limit=1")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["messageId"] == "m-2"
    assert fake.last_success_limit == 1


@pytest.mark.unit
def test_tc_api_007_get_failed_proxy_returns_reason() -> None:
    app = create_app()
    fake = _FakeNotificationClient()
    app.state.notification_client = fake
    client = TestClient(app)

    resp = client.get("/messages/failed?limit=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["reason"] == "send_failed"
    assert fake.last_failed_limit == 1


@pytest.mark.unit
def test_get_outcomes_limit_is_clamped_to_settings_max() -> None:
    app = create_app()
    fake = _FakeNotificationClient()
    app.state.notification_client = fake
    app.state.settings.inspectio_outcomes_max_limit = 3
    client = TestClient(app)

    resp = client.get("/messages/success?limit=9999")
    assert resp.status_code == 200
    assert fake.last_success_limit == 3
