"""Notification service + API outcomes (plans/TESTS.md §4.5, §5).

Skipped until notification service + Redis + API wiring per NOTIFICATION_SERVICE.md.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(
    reason="§4.5: durable terminal S3 write then worker publish → notification → Redis"
)
def test_publish_after_durable_terminal_write() -> None:
    """state/notifications/... + Redis update after terminal persistence."""


@pytest.mark.skip(
    reason="§4.5: API calls notification HTTP; no broad state/success|failed list per GET"
)
def test_api_get_outcomes_uses_notification_service_not_terminal_listing() -> None:
    """Spy: GET /messages/success does not list-prefix assemble from S3 terminal trees."""


@pytest.mark.skip(reason="§4.5: notification startup hydrates Redis from S3 up to HYDRATION_MAX")
def test_notification_service_hydration_order_and_cap() -> None:
    """Cold path only; bounded newest rows."""
