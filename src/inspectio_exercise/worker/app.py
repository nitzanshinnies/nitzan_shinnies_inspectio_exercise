from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from inspectio_exercise.common.health import register_healthz
from inspectio_exercise.common.http_client import peer_httpx_limits, peer_httpx_timeout
from inspectio_exercise.common.performance_logging import register_performance_logging
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.worker.config import (
    WORKER_ACTIVATE_BATCH_MAX_KEYS,
    WORKER_ACTIVATE_PENDING_BATCH_PATH,
    WORKER_ACTIVATE_PENDING_PATH,
    load_worker_settings,
)
from inspectio_exercise.worker.persistence_port import PersistenceAsyncPort
from inspectio_exercise.worker.runtime import WorkerRuntime
from inspectio_exercise.worker.staging_persistence import StagingPersistence


class ActivatePendingBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pending_key: str = Field(alias="pendingKey")


class ActivatePendingBatchBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pending_keys: list[str] = Field(alias="pendingKeys", max_length=WORKER_ACTIVATE_BATCH_MAX_KEYS)


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
        persistence_http = PersistenceHttpClient(persist_http)
        staging_redis: Redis | None = None
        persistence_port: PersistenceAsyncPort = persistence_http
        if settings.pending_staging_redis_url:
            staging_redis = Redis.from_url(
                settings.pending_staging_redis_url, decode_responses=False
            )
            await staging_redis.ping()
            persistence_port = StagingPersistence(staging_redis, persistence_http)
        app.state._staging_redis = staging_redis
        runtime = WorkerRuntime(
            notify_client=notify_http,
            persistence=persistence_port,
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
        if staging_redis is not None:
            await staging_redis.aclose()
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

    @app.post(
        WORKER_ACTIVATE_PENDING_PATH,
        tags=["internal"],
        include_in_schema=False,
        response_model=None,
    )
    async def activate_pending(
        request: Request,
        payload: ActivatePendingBody,
    ) -> dict[str, str] | Response:
        runtime = getattr(request.app.state, "worker_runtime", None)
        if runtime is None:
            raise HTTPException(status_code=503, detail="worker runtime not ready")
        status = await runtime.activate_pending_now(payload.pending_key)
        if status == "not_owner":
            raise HTTPException(status_code=403, detail="shard not owned by this worker")
        if status == "missing":
            return Response(status_code=204)
        if status == "invalid":
            raise HTTPException(status_code=400, detail="invalid pending key or record")
        return {"status": status}

    @app.post(
        WORKER_ACTIVATE_PENDING_BATCH_PATH,
        tags=["internal"],
        include_in_schema=False,
    )
    async def activate_pending_batch(
        request: Request,
        payload: ActivatePendingBatchBody,
    ) -> dict[str, int]:
        runtime = getattr(request.app.state, "worker_runtime", None)
        if runtime is None:
            raise HTTPException(status_code=503, detail="worker runtime not ready")
        return await runtime.activate_pending_batch(payload.pending_keys)

    return app


app = create_app()
