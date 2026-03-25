"""Shared fixtures for in-process ASGI integration tests (plans/TESTS.md §5)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from inspectio_exercise.api.app import create_app as create_api
from inspectio_exercise.health_monitor.app import create_app as create_health_monitor
from inspectio_exercise.mock_sms.app import create_app as create_mock_sms
from inspectio_exercise.notification.app import create_app as create_notification
from inspectio_exercise.persistence.app import create_app as create_persistence
from inspectio_exercise.worker.app import create_app as create_worker

SERVICE_FACTORIES: list[tuple[Callable[[], FastAPI], str]] = [
    (create_api, "api"),
    (create_health_monitor, "health_monitor"),
    (create_mock_sms, "mock_sms"),
    (create_notification, "notification"),
    (create_persistence, "persistence"),
    (create_worker, "worker"),
]


@pytest.fixture
def persistence_client() -> TestClient:
    return TestClient(create_persistence())


@pytest.fixture
def notification_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("OUTCOMES_STORE_BACKEND", "memory")
    return TestClient(create_notification())


@pytest.fixture
def health_monitor_client() -> TestClient:
    return TestClient(create_health_monitor())
