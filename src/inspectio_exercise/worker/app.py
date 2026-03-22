from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from inspectio_exercise.common.health import register_healthz
from inspectio_exercise.common.http_client import peer_httpx_limits, peer_httpx_timeout
from inspectio_exercise.common.performance_logging import register_performance_logging
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.worker.config import WORKER_ACTIVATE_PENDING_PATH, load_worker_settings
from inspectio_exercise.worker.runtime import WorkerRuntime


def _lifespan_with_clients(
    *,
    test_notify_client: httpx.AsyncClient | None,
    test_persistence_client: httpx.AsyncClient | None,
    test_sms_client: httpx.AsyncClient | None,
):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = load_worker_settings()
        created_persist = test_persistence_client is None
        created_sms = test_sms_client is None
        created_notify = test_notify_client is None
        peer_timeout = peer_httpx_timeout(total_sec=settings.http_timeout_sec)
        peer_limits = peer_httpx_limits()
        persist_http = (
            test_persistence_client
            if test_persistence_client is not None
            else httpx.AsyncClient(
                base_url=settings.persistence_url,
                limits=peer_limits,
                timeout=peer_timeout,
            )
        )
        sms_http = (
            test_sms_client
            if test_sms_client is not None
            else httpx.AsyncClient(
                base_url=settings.mock_sms_url,
                limits=peer_limits,
                timeout=peer_timeout,
            )
        )
        notify_http = (
            test_notify_client
            if test_notify_client is not None
            else httpx.AsyncClient(
                base_url=settings.notification_url,
                limits=peer_limits,
                timeout=peer_timeout,
            )
        )
        persistence = PersistenceHttpClient(persist_http)
        runtime = WorkerRuntime(
            notify_client=notify_http,
            persistence=persistence,
            settings=settings,
            sms_client=sms_http,
        )
        app.state.worker_runtime = runtime
        stop = asyncio.Event()
        task = asyncio.create_task(runtime.run_forever(stop), name="worker-scheduler")
        yield
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if created_persist:
            await persist_http.aclose()
        if created_sms:
            await sms_http.aclose()
        if created_notify:
            await notify_http.aclose()

    return lifespan


def create_app(
    *,
    test_notify_client: httpx.AsyncClient | None = None,
    test_persistence_client: httpx.AsyncClient | None = None,
    test_sms_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """HTTP for probes; shard scheduler runs as background task (plans/CORE_LIFECYCLE.md).

    For in-process E2E tests, pass ASGI ``httpx.AsyncClient`` instances for peer services.
    """
    app = FastAPI(
        title="Inspectio Worker",
        version="0.1.0",
        description="Shard-scoped scheduler — see plans/CORE_LIFECYCLE.md; HOSTNAME derives pod index.",
        lifespan=_lifespan_with_clients(
            test_notify_client=test_notify_client,
            test_persistence_client=test_persistence_client,
            test_sms_client=test_sms_client,
        ),
    )
    register_healthz(app, "worker")
    register_performance_logging(app, component="worker")

    class ActivatePendingBody(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        pending_key: str = Field(alias="pendingKey")

    @app.post(
        WORKER_ACTIVATE_PENDING_PATH,
        tags=["internal"],
        include_in_schema=False,
        response_model=None,
    )
    async def activate_pending(
        body: ActivatePendingBody,
        request: Request,
    ) -> dict[str, str] | Response:
        runtime = getattr(request.app.state, "worker_runtime", None)
        if runtime is None:
            raise HTTPException(status_code=503, detail="worker runtime not ready")
        status = await runtime.activate_pending_now(body.pending_key)
        if status == "not_owner":
            raise HTTPException(status_code=403, detail="shard not owned by this worker")
        if status == "missing":
            return Response(status_code=204)
        if status == "invalid":
            raise HTTPException(status_code=400, detail="invalid pending key or record")
        return {"status": status}

    return app


app = create_app()
