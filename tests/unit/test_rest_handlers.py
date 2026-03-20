"""REST API contracts (plans/TESTS.md §4.7) — skeleton returns 501 for message routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from inspectio_exercise.api.app import create_app


@pytest.fixture
def api_client() -> TestClient:
    return TestClient(create_app())


@pytest.mark.unit
def test_get_healthz_ok(api_client: TestClient) -> None:
    response = api_client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["service"] == "api"


@pytest.mark.unit
def test_post_messages_not_implemented(api_client: TestClient) -> None:
    response = api_client.post("/messages", json={"to": "x", "body": "y"})
    assert response.status_code == 501


@pytest.mark.unit
def test_get_messages_success_not_implemented(api_client: TestClient) -> None:
    response = api_client.get("/messages/success")
    assert response.status_code == 501


@pytest.mark.unit
def test_get_messages_failed_not_implemented(api_client: TestClient) -> None:
    response = api_client.get("/messages/failed")
    assert response.status_code == 501


@pytest.mark.unit
def test_post_messages_repeat_not_implemented(api_client: TestClient) -> None:
    response = api_client.post("/messages/repeat?count=3")
    assert response.status_code == 501
