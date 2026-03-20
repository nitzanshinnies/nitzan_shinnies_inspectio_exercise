"""Notification service + outcomes path (TESTS.md §4.5, §5)."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from inspectio_exercise.notification.app import create_app

pytestmark = pytest.mark.integration


def test_notification_outcome_endpoints_stub_501() -> None:
    """Internal outcome routes exist; not implemented (skeleton)."""
    client = TestClient(create_app())
    assert client.get("/internal/v1/outcomes/success").status_code == 501
    assert client.get("/internal/v1/outcomes/failed").status_code == 501
    assert client.post("/internal/v1/outcomes").status_code == 501


@pytest.mark.skip(reason="TESTS.md §4.5: durable terminal write + worker publish + Redis")
def test_publish_after_durable_terminal_write() -> None:
    """Worker → notification → notifications key + Redis."""


@pytest.mark.skip(reason="TESTS.md §4.5: API must query notification HTTP, not list state/success/")
def test_api_get_outcomes_no_broad_terminal_list() -> None:
    """Spy: no broad S3 list of state/success on GET /messages/success."""


@pytest.mark.skip(reason="TESTS.md §4.5: notification startup hydration from S3 to Redis")
def test_notification_service_hydration_cap() -> None:
    """Up to HYDRATION_MAX newest rows; order contract."""
