"""Structured performance logs for latency analysis (metrics-friendly text lines)."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

DURATION_MS_DECIMALS: int = 3
HEALTHZ_PATH: str = "/healthz"
OPERATION_HTTP_REQUEST: str = "http_request"
OPERATION_INTEGRITY_CHECK_PERIODIC: str = "integrity_check_periodic"
OPERATION_OUTCOMES_HYDRATE: str = "outcomes_hydrate"
OPERATION_WORKER_TICK: str = "worker_tick"
PERF_EVENT_NAME: str = "inspectio_perf"
PERF_FIELD_TIMESTAMP_UTC: str = "timestamp_utc"

_perf_logger = logging.getLogger("inspectio_exercise.performance")


def _utc_iso_timestamp_now() -> str:
    """Wall-clock UTC time when the log record is emitted (ISO-8601, ``Z`` suffix)."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _duration_ms(start: float) -> float:
    elapsed_sec = time.perf_counter() - start
    return round(elapsed_sec * 1000.0, DURATION_MS_DECIMALS)


def log_performance(
    logger_instance: logging.Logger | None = None,
    **fields: str | int | float | bool | None,
) -> None:
    """Emit one performance line: fixed prefix + JSON payload for parsing.

    Each line includes ``timestamp_utc`` (emit time) in addition to caller fields.
    """
    log = logger_instance or _perf_logger
    payload: dict[str, Any] = {"event": PERF_EVENT_NAME, **fields}
    payload[PERF_FIELD_TIMESTAMP_UTC] = _utc_iso_timestamp_now()
    log.info("%s %s", PERF_EVENT_NAME, json.dumps(payload, separators=(",", ":"), sort_keys=True))


def duration_ms_since(start: float) -> float:
    """Wall duration in milliseconds since ``start`` from :func:`time.perf_counter`."""
    return _duration_ms(start)


def register_performance_logging(app: Any, *, component: str) -> None:
    """Attach HTTP request timing middleware (full handler latency, except ``GET /healthz``)."""
    app.add_middleware(PerformanceLoggingMiddleware, component=component)


class PerformanceLoggingMiddleware:
    """ASGI middleware: logs ``operation=http_request`` without consuming the request body."""

    def __init__(self, app: ASGIApp, *, component: str) -> None:
        self.app = app
        self._component = component

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == HEALTHZ_PATH:
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status_holder: dict[str, int] = {"code": 500}

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException:
            status_holder["code"] = 500
            raise
        finally:
            log_performance(
                component=self._component,
                duration_ms=_duration_ms(start),
                http_method=scope.get("method", ""),
                http_path=path,
                http_status_code=status_holder["code"],
                operation=OPERATION_HTTP_REQUEST,
            )
