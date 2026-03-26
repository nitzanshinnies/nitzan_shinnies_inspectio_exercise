"""Public API routes for admission endpoints (§15)."""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from inspectio.domain.sharding import shard_for_message
from inspectio.ingest.kinesis_producer import (
    IngestBufferOverflowError,
    IngestProducer,
    IngestPutInput,
    IngestPutResult,
    IngestUnavailableError,
)
from inspectio.settings import Settings

DEFAULT_SUCCESS_LIST_LIMIT = 100
MAX_PUT_RECORDS_BATCH = 500
HTTP_BAD_REQUEST = 400
HTTP_SERVICE_UNAVAILABLE = 503
HTTP_TOO_MANY_REQUESTS = 429
HTTP_ACCEPTED = 202

router = APIRouter()


class PostMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str
    to: str | None = None


class PostMessagePartialRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str | None = None
    to: str | None = None


class PostMessageAccepted(BaseModel):
    message_id: str = Field(alias="messageId")
    shard_id: int = Field(alias="shardId")
    ingest_sequence: str | None = Field(default=None, alias="ingestSequence")


class PostMessagesRepeatAccepted(BaseModel):
    accepted: int
    message_ids: list[str] = Field(alias="messageIds")
    shard_ids: list[int] = Field(alias="shardIds")


def _clean_body(raw: str) -> str:
    body = raw.strip()
    if not body:
        raise HTTPException(
            status_code=HTTP_BAD_REQUEST, detail="body must be non-empty"
        )
    return body


def _parse_post_message_payload(raw_payload: dict[str, Any]) -> PostMessageRequest:
    payload = PostMessagePartialRequest.model_validate(raw_payload)
    if payload.body is None:
        raise HTTPException(status_code=HTTP_BAD_REQUEST, detail="body is required")
    return PostMessageRequest(body=payload.body, to=payload.to)


def _resolve_to(request_to: str | None, settings: Settings) -> str:
    if request_to is None or not request_to.strip():
        return settings.inspectio_default_to_e164
    return request_to


def _get_settings(request: Request) -> Settings:
    return request.app.state.settings


def _get_producer(request: Request) -> IngestProducer:
    return request.app.state.kinesis_producer


def _new_message_input(
    payload: PostMessageRequest,
    settings: Settings,
) -> IngestPutInput:
    body = _clean_body(payload.body)
    message_id = str(uuid.uuid4())
    now_ms = int(time.time() * 1000)
    shard_id = shard_for_message(message_id, settings.inspectio_total_shards)
    return IngestPutInput(
        idempotency_key=message_id,
        message_id=message_id,
        payload_body=body,
        payload_to=_resolve_to(payload.to, settings),
        received_at_ms=now_ms,
        shard_id=shard_id,
    )


def _not_implemented() -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"detail": "not_implemented", "ref": "plans/IMPLEMENTATION_PHASES.md"},
    )


def _map_ingest_exception(exc: Exception) -> JSONResponse:
    if isinstance(exc, IngestBufferOverflowError):
        return JSONResponse(
            status_code=HTTP_TOO_MANY_REQUESTS,
            content={"error": "ingest_overflow"},
        )
    return JSONResponse(
        status_code=HTTP_SERVICE_UNAVAILABLE,
        content={"error": "ingest_unavailable"},
    )


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@router.post("/messages", status_code=HTTP_ACCEPTED)
async def post_messages(
    raw_payload: dict[str, Any],
    settings: Annotated[Settings, Depends(_get_settings)],
    producer: Annotated[IngestProducer, Depends(_get_producer)],
) -> dict[str, object]:
    payload = _parse_post_message_payload(raw_payload)
    row = _new_message_input(payload, settings)
    try:
        written = await producer.put_messages([row])
    except (IngestBufferOverflowError, IngestUnavailableError) as exc:
        return _map_ingest_exception(exc)
    response = PostMessageAccepted(
        messageId=written[0].message_id,
        shardId=written[0].shard_id,
        ingestSequence=written[0].ingest_sequence,
    )
    return response.model_dump(mode="json", by_alias=True)


@router.post("/messages/repeat", status_code=HTTP_ACCEPTED)
async def post_messages_repeat(
    raw_payload: dict[str, Any],
    settings: Annotated[Settings, Depends(_get_settings)],
    producer: Annotated[IngestProducer, Depends(_get_producer)],
    count: int,
) -> dict[str, object]:
    payload = _parse_post_message_payload(raw_payload)
    if count < 1:
        raise HTTPException(status_code=HTTP_BAD_REQUEST, detail="count must be >= 1")
    if count > settings.inspectio_repeat_max_count:
        raise HTTPException(
            status_code=HTTP_BAD_REQUEST,
            detail=f"count must be <= {settings.inspectio_repeat_max_count}",
        )
    rows = [_new_message_input(payload, settings) for _ in range(count)]
    written: list[IngestPutResult] = []
    for start in range(0, len(rows), MAX_PUT_RECORDS_BATCH):
        chunk = rows[start : start + MAX_PUT_RECORDS_BATCH]
        try:
            chunk_written = await producer.put_messages(chunk)
        except (IngestBufferOverflowError, IngestUnavailableError) as exc:
            return _map_ingest_exception(exc)
        written.extend(chunk_written)
    response = PostMessagesRepeatAccepted(
        accepted=len(written),
        messageIds=[item.message_id for item in written],
        shardIds=[item.shard_id for item in written],
    )
    return response.model_dump(mode="json", by_alias=True)


@router.get("/messages/success")
async def get_messages_success(
    limit: Annotated[int, Query(ge=1)] = DEFAULT_SUCCESS_LIST_LIMIT,
) -> JSONResponse:
    _ = limit
    return _not_implemented()


@router.get("/messages/failed")
async def get_messages_failed(
    limit: Annotated[int, Query(ge=1)] = DEFAULT_SUCCESS_LIST_LIMIT,
) -> JSONResponse:
    _ = limit
    return _not_implemented()
