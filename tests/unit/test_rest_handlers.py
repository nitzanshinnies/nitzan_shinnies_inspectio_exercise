"""REST API contract (plans/REST_API.md §3).

Strict TDD: these tests **fail** until the API implements validation, persistence,
notification-service outcomes, and documented response shapes — not stub 501s.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


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
    """REST_API.md §3.2 — summary of accepted count and identifiers."""
    response = api_client.post("/messages/repeat", json={"count": 3})
    assert response.status_code == 200
    data = response.json()
    assert data.get("accepted") == 3
    assert "messageIds" in data
    assert len(data["messageIds"]) == 3


@pytest.mark.unit
def test_post_messages_repeat_missing_count_rejected(api_client: TestClient) -> None:
    response = api_client.post("/messages/repeat", json={})
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_repeat_invalid_count_rejected(api_client: TestClient) -> None:
    response = api_client.post("/messages/repeat", json={"count": 0})
    assert response.status_code == 422
