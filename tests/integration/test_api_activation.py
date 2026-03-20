"""API → pending → activation (TESTS.md §5.3)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_post_messages_stub_501(api_client) -> None:
    """Skeleton API returns 501 until POST /messages is implemented."""
    response = api_client.post("/messages", json={"to": "+1", "body": "hi"})
    assert response.status_code == 501


def test_get_outcomes_stubs_501(api_client) -> None:
    response = api_client.get("/messages/success")
    assert response.status_code == 501
    assert api_client.get("/messages/failed").status_code == 501


def test_post_repeat_stub_501(api_client) -> None:
    assert api_client.post("/messages/repeat?count=1").status_code == 501


@pytest.mark.skip(reason="TESTS.md §5.3: persistence + shard_id + PUT pending JSON")
def test_post_messages_creates_pending_under_shard_prefix() -> None:
    """POST /messages creates state/pending/shard-<shard_id>/<messageId>.json."""


@pytest.mark.skip(reason="TESTS.md §5.3: worker + mock SMS harness")
def test_activation_attempt_one_mock_outcome() -> None:
    """2xx → success path; 5xx → retry with nextDueAt in pending."""
