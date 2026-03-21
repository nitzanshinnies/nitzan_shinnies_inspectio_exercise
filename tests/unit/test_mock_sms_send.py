"""Mock SMS POST /send + audit (plans/MOCK_SMS.md §3, §8)."""

from __future__ import annotations

from unittest import mock

import pytest
from fastapi.testclient import TestClient

from inspectio_exercise.mock_sms import config as mock_config
from inspectio_exercise.mock_sms.app import create_app

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_audit_sends_returns_newest_first(client: TestClient) -> None:
    client.post("/send", json={"to": "a", "body": "one", "messageId": "m-first"})
    client.post("/send", json={"to": "b", "body": "two", "messageId": "m-second"})
    rows = client.get("/audit/sends", params={"limit": 10})
    assert rows.status_code == 200
    data = rows.json()
    assert data[0]["messageId"] == "m-second"
    assert data[1]["messageId"] == "m-first"


def test_send_rejects_empty_to(client: TestClient) -> None:
    response = client.post("/send", json={"to": "", "body": "x"})
    assert response.status_code == 400


def test_send_should_fail_is_5xx(client: TestClient) -> None:
    response = client.post(
        "/send",
        json={"to": "+1", "body": "hi", "shouldFail": True, "messageId": "x", "attemptIndex": 0},
    )
    assert response.status_code >= 500
    body = response.json()
    assert "code" in body or "error" in body


def test_send_success_200(client: TestClient) -> None:
    with mock.patch.object(mock_config, "FAILURE_RATE", 0.0):
        response = client.post(
            "/send",
            json={"to": "+1", "body": "hi", "messageId": "ok-1", "attemptIndex": 0},
        )
    assert response.status_code == 200
    assert response.json().get("ok") is True
