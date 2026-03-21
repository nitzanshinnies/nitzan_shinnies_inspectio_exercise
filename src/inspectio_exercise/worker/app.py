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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_worker_settings()
    persist_http = httpx.AsyncClient(
        base_url=settings.persistence_url,
        timeout=settings.http_timeout_sec,
    )
    sms_http = httpx.AsyncClient(
        base_url=settings.mock_sms_url,
        timeout=settings.http_timeout_sec,
    )
    notify_http = httpx.AsyncClient(
        base_url=settings.notification_url,
        timeout=settings.http_timeout_sec,
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
    await persist_http.aclose()
    await sms_http.aclose()
    await notify_http.aclose()


def create_app() -> FastAPI:
    """HTTP for probes; shard scheduler runs as background task (plans/CORE_LIFECYCLE.md)."""
    app = FastAPI(
        title="Inspectio Worker",
        version="0.1.0",
        description="Shard-scoped scheduler — see plans/CORE_LIFECYCLE.md; HOSTNAME derives pod index.",
        lifespan=lifespan,
    )
    register_healthz(app, "worker")
    return app


app = create_app()
