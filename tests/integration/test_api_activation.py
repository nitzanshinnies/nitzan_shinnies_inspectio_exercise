"""API → pending → activation (plans/TESTS.md §5.3, REST_API.md §3).

Asserts public REST contract; fails until API implements validation + handlers (TDD).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


def test_post_messages_returns_accepted_metadata(api_client) -> None:
    """§5.3 / REST_API §3.1 — accepted message metadata including messageId; pending (or accepted) state."""
    response = api_client.post("/messages", json={"recipient": "+1", "body": "hi"})
    assert response.status_code == 202
    data = response.json()
    assert "messageId" in data
    uuid.UUID(str(data["messageId"]))
    assert data.get("status") == "pending"


def test_get_outcomes_return_200_with_items(api_client) -> None:
    """REST_API §3.3–3.4 — recent outcomes; default limit when omitted."""
    response = api_client.get("/messages/success")
    assert response.status_code == 200
    assert "items" in response.json()
    assert api_client.get("/messages/failed").status_code == 200


def test_post_repeat_returns_summary(api_client) -> None:
    """REST_API §3.2 — summary with accepted count and distinct messageIds."""
    response = api_client.post("/messages/repeat", json={"count": 1})
    assert response.status_code == 200
    body = response.json()
    assert body.get("accepted") == 1
    assert len(body.get("messageIds", [])) == 1


@pytest.mark.skip(
    reason="§5.3: persistence + shard_id + durable pending under state/pending/shard-*/"
)
def test_post_messages_creates_pending_under_shard_prefix() -> None:
    """POST /messages creates state/pending/shard-<shard_id>/<messageId>.json."""


@pytest.mark.skip(reason="§5.3: in-process worker + mock SMS harness for attempt #1")
def test_activation_attempt_one_mock_outcome() -> None:
    """Mock 2xx → success path; 5xx → retry with updated nextDueAt in pending."""
