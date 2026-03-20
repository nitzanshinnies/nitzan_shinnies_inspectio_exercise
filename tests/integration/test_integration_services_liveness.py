"""Multi-service liveness smoke (TESTS.md §5 — in-process compose without Docker)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from tests.integration.conftest import SERVICE_FACTORIES

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("factory,service", SERVICE_FACTORIES)
def test_each_service_healthz(factory: Callable[[], FastAPI], service: str) -> None:
    """All microservices expose GET /healthz for orchestration probes."""
    client = TestClient(factory())
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == service
