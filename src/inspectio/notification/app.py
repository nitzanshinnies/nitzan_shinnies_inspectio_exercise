from __future__ import annotations

from typing import Annotated, Literal, Protocol

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
import redis.asyncio as redis

from inspectio.notification.outcomes_store import RedisOutcomesStore
from inspectio.settings import get_settings

DEFAULT_LIMIT = 100


class OutcomesStore(Protocol):
    async def add_terminal(self, payload: dict) -> None: ...
    async def get_success(self, *, limit: int) -> list[dict]: ...
    async def get_failed(self, *, limit: int) -> list[dict]: ...


class MessageTerminalV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    message_id: str = Field(alias="messageId")
    terminal_status: Literal["success", "failed"] = Field(alias="terminalStatus")
    attempt_count: int = Field(alias="attemptCount", ge=1, le=6)
    final_timestamp_ms: int = Field(alias="finalTimestampMs")
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_reason_semantics(self) -> "MessageTerminalV1":
        if self.terminal_status == "failed" and not self.reason:
            msg = "reason is required when terminalStatus=failed"
            raise ValueError(msg)
        if self.terminal_status == "success" and self.reason is not None:
            msg = "reason must be null when terminalStatus=success"
            raise ValueError(msg)
        return self

    def to_store_payload(self) -> dict:
        return {
            "messageId": self.message_id,
            "terminalStatus": self.terminal_status,
            "attemptCount": self.attempt_count,
            "finalTimestampMs": self.final_timestamp_ms,
            "reason": self.reason,
        }


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
        try:
            typed = MessageTerminalV1.model_validate(payload)
        except ValidationError as exc:
            detail = [{"loc": err["loc"], "msg": err["msg"]} for err in exc.errors()]
            raise HTTPException(status_code=400, detail=detail) from exc
        await store.add_terminal(typed.to_store_payload())
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
