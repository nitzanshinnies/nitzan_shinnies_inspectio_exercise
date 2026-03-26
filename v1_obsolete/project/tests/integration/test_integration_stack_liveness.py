"""All services expose liveness GET /healthz (plans/TESTS.md §5, REST_API.md §3.5 minimum).

Integration-only wiring check — does not assert business logic.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.integration.conftest import SERVICE_FACTORIES

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("factory,service", SERVICE_FACTORIES)
def test_service_exposes_healthz(factory: Callable[[], FastAPI], service: str) -> None:
    client = TestClient(factory())
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == service
