"""Shared pytest configuration and fixtures (fakes, clocks, moto — add as needed)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from inspectio_exercise.api.app import create_app
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient


def _api_mock_transport() -> httpx.MockTransport:
    """Stub persistence put + notification outcome queries (no real services)."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/internal/v1/put-object":
            return httpx.Response(200, json={"status": "ok"})
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text=f"unexpected {request.url!r}")

    return httpx.MockTransport(handler)


@pytest.fixture
def api_client() -> TestClient:
    """In-process API with mocked outbound HTTP to persistence + notification."""
    persist = httpx.AsyncClient(
        transport=_api_mock_transport(),
        base_url="http://persistence",
    )
    notif = httpx.AsyncClient(
        transport=_api_mock_transport(),
        base_url="http://notification",
    )
    app = create_app(
        persistence=PersistenceHttpClient(persist),
        notification_http=notif,
    )
    with TestClient(app) as client:
        yield client
