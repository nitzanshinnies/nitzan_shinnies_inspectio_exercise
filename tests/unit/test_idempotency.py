"""Idempotency and duplicate handling (TESTS.md §4.8, CORE_LIFECYCLE §6.2)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.skip(reason="Skeleton: duplicate activation / replay (TESTS.md §4.8)")
def test_duplicate_activation_no_duplicate_terminal() -> None:
    """Same messageId must not create duplicate terminal keys."""


@pytest.mark.skip(reason="Skeleton: replay monotonic side effects (TESTS.md §4.8)")
def test_replay_after_terminal_is_monotonic() -> None:
    """No second terminal write after success or terminal failed."""


@pytest.mark.skip(reason="Skeleton: API duplicate submission policy (REST_API §5.2)")
def test_api_duplicate_submission_defined() -> None:
    """Reject vs dedupe vs idempotent accept — per product rule."""
