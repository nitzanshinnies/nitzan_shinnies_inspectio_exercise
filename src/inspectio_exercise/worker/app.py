from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from inspectio_exercise.common.health import register_healthz
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.worker.config import load_worker_settings
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
        persist_http = (
            test_persistence_client
            if test_persistence_client is not None
            else httpx.AsyncClient(
                base_url=settings.persistence_url,
                timeout=settings.http_timeout_sec,
            )
        )
        sms_http = (
            test_sms_client
            if test_sms_client is not None
            else httpx.AsyncClient(
                base_url=settings.mock_sms_url,
                timeout=settings.http_timeout_sec,
            )
        )
        notify_http = (
            test_notify_client
            if test_notify_client is not None
            else httpx.AsyncClient(
                base_url=settings.notification_url,
                timeout=settings.http_timeout_sec,
            )
        )
        persistence = PersistenceHttpClient(persist_http)
        runtime = WorkerRuntime(
            notify_client=notify_http,
            persistence=persistence,
            settings=settings,
            sms_client=sms_http,
        )
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
    return app


app = create_app()
