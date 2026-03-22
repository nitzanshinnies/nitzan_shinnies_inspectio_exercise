"""REST API contract (plans/REST_API.md §3).

Strict TDD: these tests **fail** until the API implements validation, persistence,
notification-service outcomes, and documented response shapes — not stub 501s.
"""

from __future__ import annotations

import base64
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from inspectio_exercise.api.app import create_app
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient


@pytest.mark.unit
def test_post_messages_valid_body_returns_accepted_metadata(api_client: TestClient) -> None:
    """REST_API.md §3.1 — accepted message metadata including messageId; pending or accepted state."""
    response = api_client.post("/messages", json={"body": "hello"})
    assert response.status_code == 202
    data = response.json()
    assert "messageId" in data
    uuid.UUID(str(data["messageId"]))
    assert data.get("status") == "pending"


@pytest.mark.unit
def test_post_messages_explicit_to(api_client: TestClient) -> None:
    response = api_client.post(
        "/messages",
        json={"to": "+15551234567", "body": "hello"},
    )
    assert response.status_code == 202


@pytest.mark.unit
def test_post_messages_should_fail_persisted_in_payload() -> None:
    """Optional ``shouldFail`` is stored on pending ``payload`` for the worker to forward."""
    puts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/internal/v1/put-object":
            outer = json.loads(request.content.decode("utf-8"))
            inner = json.loads(base64.b64decode(outer["body_b64"]))
            puts.append(inner)
            return httpx.Response(200, json={"status": "ok"})
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    with TestClient(app) as client:
        response = client.post("/messages", json={"body": "hello", "shouldFail": True})
    assert response.status_code == 202
    assert len(puts) == 1
    assert puts[0]["payload"]["shouldFail"] is True


@pytest.mark.unit
def test_post_messages_omits_should_fail_from_payload_when_absent() -> None:
    puts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/internal/v1/put-object":
            outer = json.loads(request.content.decode("utf-8"))
            inner = json.loads(base64.b64decode(outer["body_b64"]))
            puts.append(inner)
            return httpx.Response(200, json={"status": "ok"})
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    with TestClient(app) as client:
        response = client.post("/messages", json={"body": "hello"})
    assert response.status_code == 202
    assert "shouldFail" not in puts[0]["payload"]


@pytest.mark.unit
def test_post_messages_missing_required_fields_rejected(api_client: TestClient) -> None:
    response = api_client.post("/messages", json={"to": "+1"})
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_empty_to_rejected(api_client: TestClient) -> None:
    response = api_client.post("/messages", json={"to": "", "body": "x"})
    assert response.status_code == 422


@pytest.mark.unit
def test_get_messages_success_returns_recent_outcomes(api_client: TestClient) -> None:
    """REST_API.md §3.3 — recent successes; default limit 100 when omitted."""
    response = api_client.get("/messages/success")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.unit
def test_get_messages_success_invalid_limit_rejected(api_client: TestClient) -> None:
    response = api_client.get("/messages/success?limit=0")
    assert response.status_code == 422


@pytest.mark.unit
def test_get_messages_failed_returns_recent_outcomes(api_client: TestClient) -> None:
    response = api_client.get("/messages/failed")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.unit
def test_get_messages_failed_invalid_limit_rejected(api_client: TestClient) -> None:
    response = api_client.get("/messages/failed?limit=-1")
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_repeat_returns_summary(api_client: TestClient) -> None:
    """REST_API.md §3.2 — ``?count=N`` with message body reused N times."""
    response = api_client.post(
        "/messages/repeat?count=3",
        json={"body": "hello"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("accepted") == 3
    assert "messageIds" in data
    assert len(data["messageIds"]) == 3


@pytest.mark.unit
def test_post_messages_repeat_templates_should_fail_on_each_put() -> None:
    puts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/internal/v1/put-object":
            outer = json.loads(request.content.decode("utf-8"))
            inner = json.loads(base64.b64decode(outer["body_b64"]))
            puts.append(inner)
            return httpx.Response(200, json={"status": "ok"})
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    with TestClient(app) as client:
        response = client.post(
            "/messages/repeat?count=2",
            json={"body": "hello", "shouldFail": True},
        )
    assert response.status_code == 200
    assert len(puts) == 2
    assert all(p["payload"].get("shouldFail") is True for p in puts)


@pytest.mark.unit
def test_post_messages_repeat_missing_count_rejected(api_client: TestClient) -> None:
    response = api_client.post("/messages/repeat", json={"body": "x"})
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_repeat_invalid_count_rejected(api_client: TestClient) -> None:
    response = api_client.post("/messages/repeat?count=0", json={"body": "x"})
    assert response.status_code == 422
