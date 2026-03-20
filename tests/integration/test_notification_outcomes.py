"""Notification service + Redis + API outcomes (TESTS.md §4.5, §5.x)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Skeleton: publish after terminal S3 (TESTS.md §4.5)")
def test_publish_after_durable_terminal_write() -> None:
    """Worker → notification → notifications key + Redis."""


@pytest.mark.skip(reason="Skeleton: API queries notification only (TESTS.md §4.5)")
def test_api_get_outcomes_no_broad_terminal_list() -> None:
    """Spy: no list state/success on GET /messages/success."""


@pytest.mark.skip(reason="Skeleton: hydration from S3 to Redis (TESTS.md §4.5)")
def test_notification_service_hydration_cap() -> None:
    """Up to HYDRATION_MAX newest rows; order contract."""
