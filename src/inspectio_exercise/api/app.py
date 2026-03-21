"""Public REST API — plans/REST_API.md."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request

from inspectio_exercise.api import config
from inspectio_exercise.api.schemas import MessageCreate, RepeatMessagesCreate
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


def _message_to_query(
    to: Annotated[
        str,
        Query(
            description=(
                "Default SMS destination for this request scope; reserved for future outcome filtering."
            ),
        ),
    ] = config.DEFAULT_MESSAGE_TO,
) -> str:
    return to


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
        repeat: RepeatMessagesCreate,
        persistence_client: PersistenceHttpClient = Depends(get_persistence),
        total_shards: int = Depends(get_total_shards),
    ) -> dict[str, Any]:
        ids: list[str] = []
        try:
            for _ in range(repeat.count):
                mid = await submit_message(
                    persistence_client,
                    total_shards=total_shards,
                    to=repeat.to,
                    body=repeat.body,
                )
                ids.append(mid)
        except (httpx.HTTPError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"accepted": repeat.count, "messageIds": ids}

    @app.get("/messages/success", tags=["messages"])
    async def get_messages_success(
        limit: int = Depends(_outcome_query_limit),
        to: str = Depends(_message_to_query),
        client: httpx.AsyncClient = Depends(get_notification_http),
    ) -> dict[str, Any]:
        logger.debug("outcomes.success", extra={"to": to, "limit": limit})
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
        to: str = Depends(_message_to_query),
        client: httpx.AsyncClient = Depends(get_notification_http),
    ) -> dict[str, Any]:
        logger.debug("outcomes.failed", extra={"to": to, "limit": limit})
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
