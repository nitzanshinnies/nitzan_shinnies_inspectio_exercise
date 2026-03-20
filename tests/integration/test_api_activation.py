"""API → pending → activation path (TESTS.md §5.3)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Skeleton: POST /messages → correct shard pending (TESTS.md §5.3)")
def test_post_messages_creates_pending_under_shard_prefix() -> None:
    """messageId maps to shard_id; key under state/pending/shard-*/."""


@pytest.mark.skip(reason="Skeleton: attempt #1 with mock 2xx vs 5xx (TESTS.md §5.3)")
def test_activation_attempt_one_mock_outcome() -> None:
    """2xx → success path; 5xx → retry with nextDueAt."""
