"""Retry timeline and `nextDueAt` (TESTS.md §4.2, PLAN.md §5)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.skip(reason="Skeleton: delays +0.5s,+2s,+4s,+8s,+16s (TESTS.md §4.2)")
def test_next_due_at_per_attempt_before_terminal() -> None:
    """attemptCount 0..5 → nextDueAt matches architect timeline."""


@pytest.mark.skip(reason="Skeleton: terminal at attemptCount==6 (TESTS.md §4.2)")
def test_no_schedule_after_terminal_failure() -> None:
    """attemptCount==6 → failed terminal key; no further pending."""


@pytest.mark.skip(reason="Skeleton: failed send updates pending in place (PLAN §5)")
def test_retry_keeps_pending_prefix_with_updated_fields() -> None:
    """Status remains pending under shard until terminal move."""
