"""Public REST API — plans/REST_API.md."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request

from inspectio_exercise.api import config
from inspectio_exercise.api.schemas import MessageCreate
from inspectio_exercise.api.use_cases import (
    request_immediate_activation,
    submit_message,
    submit_messages_repeat_parallel,
    worker_activation_base_urls,
)
from inspectio_exercise.common.health import register_healthz
from inspectio_exercise.common.http_client import peer_httpx_limits, peer_httpx_timeout
from inspectio_exercise.common.performance_logging import register_performance_logging
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient

logger = logging.getLogger(__name__)


def _outcome_query_limit(
    limit: Annotated[
        int,
        Query(ge=1, le=config.OUTCOME_QUERY_LIMIT_MAX, description="Max rows to return"),
    ] = config.OUTCOME_QUERY_LIMIT_DEFAULT,
) -> int:
    return limit


def _repeat_count(
    count: Annotated[
        int,
        Query(ge=1, le=config.REPEAT_COUNT_MAX, description="How many copies to create"),
    ],
) -> int:
    return count


def create_app(
    *,
    persistence: PersistenceHttpClient | None = None,
    notification_http: httpx.AsyncClient | None = None,
    worker_activation_http: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Create the FastAPI app.

    For tests, pass ``persistence`` and ``notification_http`` (e.g. ``httpx.MockTransport``).
    Optionally pass ``worker_activation_http`` (ASGI transport to the worker) for immediate
    attempt #1. Otherwise clients are built from environment URLs.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        peer_limits = peer_httpx_limits()
        peer_timeout = peer_httpx_timeout(total_sec=config.PEER_HTTP_CLIENT_TIMEOUT_SEC)
        if persistence is None:
            persist_raw = httpx.AsyncClient(
                base_url=config.PERSISTENCE_SERVICE_URL,
                limits=peer_limits,
                timeout=peer_timeout,
            )
            app.state.persistence = PersistenceHttpClient(persist_raw)
        else:
            app.state.persistence = persistence
        if notification_http is None:
            app.state.notification_http = httpx.AsyncClient(
                base_url=config.NOTIFICATION_SERVICE_URL,
                limits=peer_limits,
                timeout=peer_timeout,
            )
        else:
            app.state.notification_http = notification_http
        app.state.total_shards = config.TOTAL_SHARDS
        app.state.worker_shards_per_pod = config.WORKER_SHARDS_PER_POD_FOR_ACTIVATION
        created_worker_clients: list[httpx.AsyncClient] = []
        if worker_activation_http is not None:
            app.state.worker_activation_clients = [worker_activation_http]
            app.state._close_worker_activation_clients = False
        else:
            bases = worker_activation_base_urls()
            for base in bases:
                created_worker_clients.append(
                    httpx.AsyncClient(
                        base_url=base,
                        limits=peer_limits,
                        timeout=peer_timeout,
                    )
                )
            app.state.worker_activation_clients = created_worker_clients
            app.state._close_worker_activation_clients = bool(created_worker_clients)
        yield
        await app.state.persistence.aclose()
        await app.state.notification_http.aclose()
        if getattr(app.state, "_close_worker_activation_clients", False):
            for wc in app.state.worker_activation_clients:
                await wc.aclose()

    app = FastAPI(
        title="Inspectio REST API",
        version="0.1.0",
        description="Public API per plans/REST_API.md — persistence + notification over HTTP only.",
        lifespan=lifespan,
    )
    register_healthz(app, "api")
    register_performance_logging(app, component="api")

    def get_persistence(request: Request) -> PersistenceHttpClient:
        return request.app.state.persistence

    def get_notification_http(request: Request) -> httpx.AsyncClient:
        return request.app.state.notification_http

    def get_total_shards(request: Request) -> int:
        return int(request.app.state.total_shards)

    def get_worker_activation_clients(request: Request) -> list[httpx.AsyncClient]:
        return request.app.state.worker_activation_clients

    def get_worker_shards_per_pod(request: Request) -> int:
        return int(request.app.state.worker_shards_per_pod)

    @app.post("/messages", tags=["messages"], status_code=202)
    async def post_messages(
        body: MessageCreate,
        persistence_client: PersistenceHttpClient = Depends(get_persistence),
        total_shards: int = Depends(get_total_shards),
        worker_clients: list[httpx.AsyncClient] = Depends(get_worker_activation_clients),
        shards_per_pod: int = Depends(get_worker_shards_per_pod),
    ) -> dict[str, str]:
        if len(body.body) > config.MESSAGE_BODY_MAX_CHARS:
            raise HTTPException(status_code=413, detail="message body too large")
        try:
            submitted = await submit_message(
                persistence_client,
                body=body.body,
                should_fail=body.should_fail,
                to=body.to,
                total_shards=total_shards,
            )
            await request_immediate_activation(
                worker_clients,
                submitted=submitted,
                shards_per_pod=shards_per_pod,
            )
        except (httpx.HTTPError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"messageId": submitted.message_id, "status": "pending"}

    @app.post("/messages/repeat", tags=["messages"])
    async def post_messages_repeat(
        message: MessageCreate,
        count: int = Depends(_repeat_count),
        persistence_client: PersistenceHttpClient = Depends(get_persistence),
        total_shards: int = Depends(get_total_shards),
        worker_clients: list[httpx.AsyncClient] = Depends(get_worker_activation_clients),
        shards_per_pod: int = Depends(get_worker_shards_per_pod),
    ) -> dict[str, Any]:
        """``?count=N`` with the same JSON body as ``POST /messages``, reused ``N`` times."""
        if len(message.body) > config.MESSAGE_BODY_MAX_CHARS:
            raise HTTPException(status_code=413, detail="message body too large")
        try:
            ids = await submit_messages_repeat_parallel(
                persistence_client,
                body=message.body,
                count=count,
                should_fail=message.should_fail,
                to=message.to,
                total_shards=total_shards,
                worker_clients=worker_clients,
                shards_per_pod=shards_per_pod,
                concurrency=config.REPEAT_SUBMIT_CONCURRENCY,
            )
        except (httpx.HTTPError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"accepted": count, "messageIds": ids}

    @app.get("/messages/success", tags=["messages"])
    async def get_messages_success(
        limit: int = Depends(_outcome_query_limit),
        client: httpx.AsyncClient = Depends(get_notification_http),
    ) -> dict[str, Any]:
        logger.debug("outcomes.success", extra={"limit": limit})
        try:
            response = await client.get(
                "/internal/v1/outcomes/success",
                params={"limit": limit},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code, detail=exc.response.text
            ) from exc
        except (httpx.RequestError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        items = response.json()
        return {"items": items}

    @app.get("/messages/failed", tags=["messages"])
    async def get_messages_failed(
        limit: int = Depends(_outcome_query_limit),
        client: httpx.AsyncClient = Depends(get_notification_http),
    ) -> dict[str, Any]:
        logger.debug("outcomes.failed", extra={"limit": limit})
        try:
            response = await client.get(
                "/internal/v1/outcomes/failed",
                params={"limit": limit},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code, detail=exc.response.text
            ) from exc
        except (httpx.RequestError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        items = response.json()
        return {"items": items}

    return app


app = create_app()
