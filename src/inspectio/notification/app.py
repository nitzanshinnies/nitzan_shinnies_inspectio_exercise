from __future__ import annotations

from typing import Annotated, Protocol

from fastapi import Body, Depends, FastAPI, Query, Request, Response
import redis.asyncio as redis

from inspectio.notification.outcomes_store import RedisOutcomesStore
from inspectio.settings import get_settings

DEFAULT_LIMIT = 100


class OutcomesStore(Protocol):
    async def add_terminal(self, payload: dict) -> None: ...
    async def get_success(self, *, limit: int) -> list[dict]: ...
    async def get_failed(self, *, limit: int) -> list[dict]: ...


def create_app() -> FastAPI:
    app = FastAPI(title="inspectio-notification", version="0.0.0")
    settings = get_settings()
    redis_client = redis.from_url(settings.inspectio_redis_url, decode_responses=True)
    app.state.outcomes_store = RedisOutcomesStore(
        redis_client=redis_client,
        max_items=max(100, settings.inspectio_outcomes_max_limit),
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "notification"}

    def _store(request: Request) -> OutcomesStore:
        return request.app.state.outcomes_store

    @app.post("/internal/v1/outcomes/terminal", status_code=204)
    async def post_terminal(
        payload: Annotated[dict, Body(...)],
        store: OutcomesStore = Depends(_store),
    ) -> Response:
        await store.add_terminal(payload)
        return Response(status_code=204)

    @app.get("/internal/v1/outcomes/success")
    async def get_outcomes_success(
        store: OutcomesStore = Depends(_store),
        limit: Annotated[int, Query(ge=1)] = DEFAULT_LIMIT,
    ) -> dict:
        return {"items": await store.get_success(limit=limit)}

    @app.get("/internal/v1/outcomes/failed")
    async def get_outcomes_failed(
        store: OutcomesStore = Depends(_store),
        limit: Annotated[int, Query(ge=1)] = DEFAULT_LIMIT,
    ) -> dict:
        return {"items": await store.get_failed(limit=limit)}

    return app


app = create_app()
