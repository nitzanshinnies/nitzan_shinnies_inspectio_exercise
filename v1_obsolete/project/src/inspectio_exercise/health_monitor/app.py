"""Health monitor HTTP surface (plans/HEALTH_MONITOR.md §4)."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from inspectio_exercise.common.health import register_healthz
from inspectio_exercise.common.performance_logging import (
    OPERATION_INTEGRITY_CHECK_PERIODIC,
    duration_ms_since,
    log_performance,
    register_performance_logging,
)
from inspectio_exercise.health_monitor.config import (
    HEADER_INTEGRITY_CHECK_TOKEN,
    HealthMonitorSettings,
    load_health_monitor_settings,
)
from inspectio_exercise.health_monitor.integrity_run import run_integrity_check
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient

logger = logging.getLogger(__name__)


class IntegrityCheckRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    grace_ms: int | None = Field(default=None, alias="graceMs", ge=0, le=86_400_000)


def _settings(request: Request) -> HealthMonitorSettings:
    return request.app.state.settings


def _require_integrity_token(
    request: Request, settings: HealthMonitorSettings = Depends(_settings)
) -> None:
    expected = settings.integrity_check_token
    if expected is None:
        return
    got = request.headers.get(HEADER_INTEGRITY_CHECK_TOKEN)
    if got != expected:
        raise HTTPException(status_code=401, detail="integrity check token missing or invalid")


def _result_payload(
    *,
    ok: bool,
    checked_at: str,
    result: Any,
    violations: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "checkedAt": checked_at,
        "ok": ok,
        "summary": {
            "auditRows": result.audit_row_count,
            "graceMs": result.grace_ms,
            "lifecycleJsonKeysExamined": result.lifecycle_json_keys_examined,
            "lifecycleObjectsParsed": result.lifecycle_object_count,
            "violations": len(violations),
        },
        "violations": violations,
    }


def create_app(
    *,
    persistence: PersistenceHttpClient | None = None,
    mock_sms: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Create the FastAPI app.

    For tests, pass ``persistence`` and ``mock_sms`` (e.g. ``httpx.ASGITransport`` clients).
    The app will not close injected clients on shutdown.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = load_health_monitor_settings()
        app.state.settings = settings
        app.state.last_integrity_payload: dict[str, Any] | None = None
        created_persistence = persistence is None
        created_mock = mock_sms is None
        if persistence is not None:
            app.state.persistence = persistence
        else:
            p_raw = httpx.AsyncClient(
                base_url=settings.persistence_url,
                timeout=settings.http_timeout_sec,
            )
            app.state.persistence = PersistenceHttpClient(p_raw)
            app.state._persistence_httpx = p_raw
        if mock_sms is not None:
            app.state.mock_sms = mock_sms
        else:
            m_raw = httpx.AsyncClient(
                base_url=settings.mock_sms_url,
                timeout=settings.http_timeout_sec,
            )
            app.state.mock_sms = m_raw
            app.state._mock_httpx = m_raw

        poll_task: asyncio.Task[None] | None = None

        async def _poll_loop() -> None:
            while True:
                await asyncio.sleep(settings.poll_interval_sec)
                try:
                    grace = settings.default_grace_ms
                    ic_started = time.perf_counter()
                    res = await run_integrity_check(
                        persistence=app.state.persistence,
                        mock_sms=app.state.mock_sms,
                        settings=settings,
                        grace_ms=grace,
                    )
                    log_performance(
                        component="health_monitor",
                        duration_ms=duration_ms_since(ic_started),
                        integrity_violation_count=len(res.violations),
                        operation=OPERATION_INTEGRITY_CHECK_PERIODIC,
                    )
                    checked_at = datetime.now(UTC).isoformat()
                    vjson = [v.as_json() for v in res.violations]
                    payload = _result_payload(
                        ok=len(res.violations) == 0,
                        checked_at=checked_at,
                        result=res,
                        violations=vjson,
                    )
                    app.state.last_integrity_payload = payload
                    if res.violations:
                        logger.warning(
                            "periodic integrity_check found violations=%s",
                            len(res.violations),
                        )
                except Exception:
                    logger.exception("periodic integrity_check failed")

        if settings.enable_periodic_reconcile:
            poll_task = asyncio.create_task(_poll_loop())

        try:
            yield
        finally:
            if poll_task is not None:
                poll_task.cancel()
                with suppress(asyncio.CancelledError):
                    await poll_task
            if created_persistence:
                await app.state.persistence.aclose()
            if created_mock:
                await app.state.mock_sms.aclose()

    app = FastAPI(
        title="Inspectio Health Monitor",
        version="0.1.0",
        description=(
            "GET /healthz liveness; POST /internal/v1/integrity-check reconciles mock audit vs "
            "persistence read API (S3 or local backend) - plans/HEALTH_MONITOR.md."
        ),
        lifespan=lifespan,
    )
    register_healthz(app, "health_monitor")
    register_performance_logging(app, component="health_monitor")

    @app.post(
        "/internal/v1/integrity-check",
        tags=["internal"],
        response_model=None,
    )
    async def post_integrity_check(
        request: Request,
        body: IntegrityCheckRequest | None = None,
        _: None = Depends(_require_integrity_token),
    ) -> JSONResponse | dict[str, Any]:
        """Run one reconciliation. On dependency errors, ``503`` uses a smaller JSON body than violation responses."""
        settings: HealthMonitorSettings = request.app.state.settings
        grace = (
            settings.default_grace_ms if body is None or body.grace_ms is None else body.grace_ms
        )
        try:
            result = await run_integrity_check(
                persistence=request.app.state.persistence,
                mock_sms=request.app.state.mock_sms,
                settings=settings,
                grace_ms=grace,
            )
        except httpx.HTTPError as exc:
            logger.exception("integrity_check upstream HTTP failure")
            raise HTTPException(
                status_code=503,
                detail={"reason": "upstream_unreachable", "error": str(exc)},
            ) from exc
        except (TypeError, ValueError) as exc:
            logger.exception("integrity_check protocol error")
            raise HTTPException(
                status_code=503,
                detail={"reason": "upstream_protocol_error", "error": str(exc)},
            ) from exc

        checked_at = datetime.now(UTC).isoformat()
        violations = [v.as_json() for v in result.violations]
        payload = _result_payload(
            ok=len(violations) == 0,
            checked_at=checked_at,
            result=result,
            violations=violations,
        )
        request.app.state.last_integrity_payload = payload
        if violations:
            return JSONResponse(status_code=503, content=payload)
        return payload

    @app.get("/internal/v1/integrity-status", tags=["internal"])
    async def get_integrity_status(request: Request) -> dict[str, Any]:
        """Cached last POST result; no auth (rely on network policy per HEALTH_MONITOR.md 4.3)."""
        last = request.app.state.last_integrity_payload
        if last is None:
            return {"lastRun": None}
        return {"lastRun": last}

    return app


app = create_app()
