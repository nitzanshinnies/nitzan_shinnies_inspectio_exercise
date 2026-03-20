"""Smoke: `GET /healthz` on all FastAPI services (plans/TESTS.md §4.7, §9)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from inspectio_exercise.api.app import create_app as create_api
from inspectio_exercise.health_monitor.app import create_app as create_health_monitor
from inspectio_exercise.mock_sms.app import create_app as create_mock_sms
from inspectio_exercise.notification.app import create_app as create_notification
from inspectio_exercise.persistence.app import create_app as create_persistence
from inspectio_exercise.worker.app import create_app as create_worker


@pytest.mark.parametrize(
    ("factory", "service"),
    [
        (create_api, "api"),
        (create_health_monitor, "health_monitor"),
        (create_mock_sms, "mock_sms"),
        (create_notification, "notification"),
        (create_persistence, "persistence"),
        (create_worker, "worker"),
    ],
)
@pytest.mark.unit
def test_healthz(factory: Callable[[], FastAPI], service: str) -> None:
    """Liveness smoke: `register_healthz` (plans/REST_API.md §3.5 exercise minimum). Readiness is separate."""
    client = TestClient(factory())
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == service
