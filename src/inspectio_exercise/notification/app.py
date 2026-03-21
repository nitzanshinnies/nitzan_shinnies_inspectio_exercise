"""Outcomes notification service — publish + query (plans/NOTIFICATION_SERVICE.md)."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from pydantic.config import ConfigDict
from redis import asyncio as redis_asyncio
from redis.asyncio import Redis
from redis.exceptions import RedisError

from inspectio_exercise.common.health import register_healthz
from inspectio_exercise.common.http_client import HTTP_CLIENT_TIMEOUT_SEC
from inspectio_exercise.notification import config
from inspectio_exercise.notification.outcomes import hydrate_from_persistence, publish_outcome
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient


class PublishOutcomeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    message_id: str = Field(alias="messageId")
    notification_id: str = Field(alias="notificationId")
    outcome: str
    recorded_at: int = Field(alias="recordedAt")
    shard_id: int = Field(alias="shardId")

    @field_validator("outcome")
    @classmethod
    def outcome_ok(cls, v: str) -> str:
        if v not in ("success", "failed"):
            raise ValueError("outcome must be 'success' or 'failed'")
        return v


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        raise HTTPException(status_code=422, detail="limit must be >= 1")
    return min(limit, config.QUERY_LIMIT_MAX)


def create_app(
    *,
    test_redis: Redis | None = None,
    test_http_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Create the FastAPI app. For tests, pass ``test_redis`` and ``test_http_client`` (e.g. ASGI transport to persistence)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        redis_url = os.environ.get("REDIS_URL", config.REDIS_URL)
        persist_url = os.environ.get("PERSISTENCE_SERVICE_URL", config.PERSISTENCE_SERVICE_URL)
        created_redis = test_redis is None
        created_http = test_http_client is None
        r = (
            test_redis
            if test_redis is not None
            else redis_asyncio.from_url(redis_url, decode_responses=True)
        )
        try:
            await r.ping()
        except RedisError as exc:
            raise RuntimeError(f"Redis unavailable at {redis_url!r}") from exc
        client = (
            test_http_client
            if test_http_client is not None
            else httpx.AsyncClient(base_url=persist_url, timeout=HTTP_CLIENT_TIMEOUT_SEC)
        )
        persistence = PersistenceHttpClient(client)
        try:
            loaded = await hydrate_from_persistence(r, persistence)
        except (httpx.HTTPError, OSError) as exc:
            if created_http:
                await persistence.aclose()
            if created_redis:
                await r.aclose()
            raise RuntimeError("hydration failed — persistence service unreachable?") from exc
        app.state.redis = r
        app.state.persistence = persistence
        app.state.hydration_count = loaded
        app.state.created_redis = created_redis
        app.state.created_http = created_http
        yield
        if created_http:
            await persistence.aclose()
        if created_redis:
            await r.aclose()

    app = FastAPI(
        title="Inspectio Notification Service",
        version="0.1.0",
        description="Publish terminal outcomes; query Redis — see plans/NOTIFICATION_SERVICE.md.",
        lifespan=lifespan,
    )
    register_healthz(app, "notification")

    def get_persistence(request: Request) -> PersistenceHttpClient:
        return request.app.state.persistence

    def get_redis(request: Request) -> Redis:
        return request.app.state.redis

    @app.post("/internal/v1/outcomes", tags=["internal"])
    async def post_outcomes(
        body: PublishOutcomeRequest,
        persistence: PersistenceHttpClient = Depends(get_persistence),
        redis: Redis = Depends(get_redis),
    ) -> dict[str, str]:
        record = body.model_dump(by_alias=True, mode="json")
        try:
            await publish_outcome(redis, persistence, record)
        except (RedisError, httpx.HTTPError, OSError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"status": "ok"}

    @app.get("/internal/v1/outcomes/failed", tags=["internal"])
    async def get_outcomes_failed(
        limit: int = config.QUERY_LIMIT_DEFAULT,
        redis: Redis = Depends(get_redis),
    ) -> list[dict[str, Any]]:
        lim = _clamp_limit(limit)
        try:
            raw_rows = await redis.lrange(config.REDIS_KEY_FAILED, 0, lim - 1)
        except RedisError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return [json.loads(x) for x in raw_rows]

    @app.get("/internal/v1/outcomes/success", tags=["internal"])
    async def get_outcomes_success(
        limit: int = config.QUERY_LIMIT_DEFAULT,
        redis: Redis = Depends(get_redis),
    ) -> list[dict[str, Any]]:
        lim = _clamp_limit(limit)
        try:
            raw_rows = await redis.lrange(config.REDIS_KEY_SUCCESS, 0, lim - 1)
        except RedisError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return [json.loads(x) for x in raw_rows]

    @app.get("/internal/v1/ready", tags=["internal"], include_in_schema=False)
    async def ready(request: Request) -> Response:
        if not hasattr(request.app.state, "redis"):
            return Response(status_code=503)
        return Response(status_code=200)

    return app


app = create_app()
