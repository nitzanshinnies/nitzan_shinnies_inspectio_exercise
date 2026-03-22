"""Performance logging middleware and structured perf lines."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from inspectio_exercise.common.performance_logging import (
    HEALTHZ_PATH,
    OPERATION_HTTP_REQUEST,
    PERF_EVENT_NAME,
    log_performance,
    register_performance_logging,
)

pytestmark = pytest.mark.unit


def test_log_performance_emits_expected_keys(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="test_perf")
    log = logging.getLogger("test_perf")
    log_performance(
        log,
        component="x",
        duration_ms=1.234,
        operation=OPERATION_HTTP_REQUEST,
        http_method="GET",
        http_path="/y",
        http_status_code=200,
    )
    assert len(caplog.records) == 1
    msg = caplog.records[0].getMessage()
    assert PERF_EVENT_NAME in msg
    payload = json.loads(msg[msg.index("{") :])
    assert payload["event"] == PERF_EVENT_NAME
    assert payload["component"] == "x"
    assert payload["operation"] == OPERATION_HTTP_REQUEST
    assert payload["duration_ms"] == 1.234
    assert payload["http_status_code"] == 200


def test_performance_middleware_logs_request(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="inspectio_exercise.performance")
    app = FastAPI()

    @app.get("/work")
    async def work() -> dict[str, str]:
        return {"ok": "1"}

    register_performance_logging(app, component="test_service")
    client = TestClient(app)
    response = client.get("/work")
    assert response.status_code == 200
    perf_lines = [r.getMessage() for r in caplog.records if PERF_EVENT_NAME in r.getMessage()]
    assert len(perf_lines) == 1
    line = perf_lines[0]
    payload = json.loads(line[line.index("{") :])
    assert payload["component"] == "test_service"
    assert payload["operation"] == OPERATION_HTTP_REQUEST
    assert payload["http_path"] == "/work"
    assert payload["http_method"] == "GET"
    assert payload["http_status_code"] == 200
    assert "duration_ms" in payload


def test_performance_middleware_skips_healthz(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="inspectio_exercise.performance")
    app = FastAPI()

    @app.get(HEALTHZ_PATH)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    register_performance_logging(app, component="test_service")
    client = TestClient(app)
    response = client.get(HEALTHZ_PATH)
    assert response.status_code == 200
    perf_lines = [r for r in caplog.records if PERF_EVENT_NAME in r.getMessage()]
    assert perf_lines == []
