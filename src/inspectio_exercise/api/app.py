"""Public REST API — plans/REST_API.md."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from inspectio_exercise.api import config
from inspectio_exercise.api.operational_ui import OPERATIONAL_HTML
from inspectio_exercise.api.schemas import MessageCreate
from inspectio_exercise.api.use_cases import submit_message
from inspectio_exercise.common.health import register_healthz
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
) -> FastAPI:
    """Create the FastAPI app.

    For tests, pass ``persistence`` and ``notification_http`` (e.g. ``httpx.MockTransport``).
    Otherwise clients are built from ``PERSISTENCE_SERVICE_URL`` and ``NOTIFICATION_SERVICE_URL``.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if persistence is None:
            persist_raw = httpx.AsyncClient(
                base_url=config.PERSISTENCE_SERVICE_URL,
                timeout=60.0,
            )
            app.state.persistence = PersistenceHttpClient(persist_raw)
        else:
            app.state.persistence = persistence
        if notification_http is None:
            app.state.notification_http = httpx.AsyncClient(
                base_url=config.NOTIFICATION_SERVICE_URL,
                timeout=60.0,
            )
        else:
            app.state.notification_http = notification_http
        app.state.total_shards = config.TOTAL_SHARDS
        yield
        await app.state.persistence.aclose()
        await app.state.notification_http.aclose()

    app = FastAPI(
        title="Inspectio REST API",
        version="0.1.0",
        description="Public API per plans/REST_API.md — persistence + notification over HTTP only.",
        lifespan=lifespan,
    )
    register_healthz(app, "api")

    @app.get("/", include_in_schema=False)
    async def operational_page() -> HTMLResponse:
        """Minimal HTML hitting the exercise REST routes (optional operational surface)."""
        return HTMLResponse(OPERATIONAL_HTML)

    def get_persistence(request: Request) -> PersistenceHttpClient:
        return request.app.state.persistence

    def get_notification_http(request: Request) -> httpx.AsyncClient:
        return request.app.state.notification_http

    def get_total_shards(request: Request) -> int:
        return int(request.app.state.total_shards)

    @app.post("/messages", tags=["messages"], status_code=202)
    async def post_messages(
        body: MessageCreate,
        persistence_client: PersistenceHttpClient = Depends(get_persistence),
        total_shards: int = Depends(get_total_shards),
    ) -> dict[str, str]:
        try:
            message_id = await submit_message(
                persistence_client,
                total_shards=total_shards,
                to=body.to,
                body=body.body,
            )
        except (httpx.HTTPError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"messageId": message_id, "status": "pending"}

    @app.post("/messages/repeat", tags=["messages"])
    async def post_messages_repeat(
        message: MessageCreate,
        count: int = Depends(_repeat_count),
        persistence_client: PersistenceHttpClient = Depends(get_persistence),
        total_shards: int = Depends(get_total_shards),
    ) -> dict[str, Any]:
        """``?count=N`` with the same JSON body as ``POST /messages``, reused ``N`` times."""
        ids: list[str] = []
        try:
            for _ in range(count):
                mid = await submit_message(
                    persistence_client,
                    total_shards=total_shards,
                    to=message.to,
                    body=message.body,
                )
                ids.append(mid)
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
