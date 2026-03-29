"""Notification service: internal terminal ingest + Redis-backed GET lists ."""

from __future__ import annotations

from typing import Any

import redis.asyncio as redis
from fastapi import Depends, FastAPI, Query, Request, Response
from pydantic import BaseModel, Field

from inspectio.notification.outcomes_store import OutcomesStore
from inspectio.settings import Settings


class MessageTerminalV1(BaseModel):
    message_id: str = Field(alias="messageId")
    terminal_status: str = Field(alias="terminalStatus")
    attempt_count: int = Field(alias="attemptCount", ge=1, le=6)
    final_timestamp_ms: int = Field(alias="finalTimestampMs")
    reason: str | None = None

    model_config = {"populate_by_name": True}


_settings = Settings()
_redis = redis.from_url(_settings.redis_url, decode_responses=False)
_store = OutcomesStore(_redis)

app = FastAPI(title="inspectio-notification", version="0.0.0")
app.state.settings = _settings
app.state.outcomes_store = _store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> OutcomesStore:
    return request.app.state.outcomes_store


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "notification"}


@app.post("/internal/v1/outcomes/terminal")
async def post_terminal(
    body: MessageTerminalV1,
    store: OutcomesStore = Depends(get_store),
) -> Response:
    row: dict[str, Any] = {
        "messageId": body.message_id,
        "terminalStatus": body.terminal_status,
        "attemptCount": body.attempt_count,
        "finalTimestampMs": body.final_timestamp_ms,
        "reason": body.reason,
    }
    await store.record_terminal(row)
    return Response(status_code=204)


def _clamp_limit(raw: int, settings: Settings) -> int:
    return max(1, min(raw, settings.outcomes_max_limit))


def _public_items(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for r in rows:
        items.append(
            {
                "messageId": r["messageId"],
                "attemptCount": r["attemptCount"],
                "finalTimestamp": r["finalTimestampMs"],
                "reason": r.get("reason"),
            }
        )
    return {"items": items}


@app.get("/internal/v1/outcomes/success")
async def get_outcomes_success(
    limit: int = Query(..., ge=1),
    store: OutcomesStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    lim = _clamp_limit(limit, settings)
    rows = await store.list_success(lim)
    return _public_items(rows)


@app.get("/internal/v1/outcomes/failed")
async def get_outcomes_failed(
    limit: int = Query(..., ge=1),
    store: OutcomesStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    lim = _clamp_limit(limit, settings)
    rows = await store.list_failed(lim)
    return _public_items(rows)
