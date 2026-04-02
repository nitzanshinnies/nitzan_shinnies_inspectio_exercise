"""Public HTTP routes ."""

from __future__ import annotations

import time
import uuid
from typing import Annotated

import httpx
import orjson
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, Response

from inspectio.domain.sharding import shard_for_message
from inspectio.ingest.ingest_producer import IngestPutInput, IngestUnavailableError
from inspectio.ingest.sqs_fifo_producer import SqsFifoIngestProducer

router = APIRouter()


def _trim_body(body: str) -> str:
    s = body.strip()
    if not s:
        raise HTTPException(status_code=400, detail="body must be non-empty after trim")
    return s


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@router.post("/messages", status_code=status.HTTP_202_ACCEPTED)
async def post_messages(
    request: Request,
    payload: dict,
) -> dict:
    settings = request.app.state.settings
    producer: SqsFifoIngestProducer = request.app.state.ingest_producer
    body_raw = payload.get("body")
    if not isinstance(body_raw, str):
        raise HTTPException(status_code=400, detail="body must be a string")
    body = _trim_body(body_raw)
    to_val = payload.get("to")
    payload_to = str(to_val) if to_val is not None else None
    mid = str(uuid.uuid4())
    shard = shard_for_message(mid, settings.total_shards)
    now = int(time.time() * 1000)
    item = IngestPutInput(
        message_id=mid,
        shard_id=shard,
        payload_body=body,
        payload_to=payload_to,
        received_at_ms=now,
        idempotency_key=mid,
    )
    try:
        results = await producer.put_messages([item])
    except IngestUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": "ingest_unavailable", "detail": str(exc)},
        )
    r0 = results[0]
    return {
        "messageId": r0.message_id,
        "shardId": r0.shard_id,
        "ingestSequence": r0.ingest_sequence,
    }


@router.post("/messages/repeat", status_code=status.HTTP_202_ACCEPTED)
async def post_messages_repeat(
    request: Request,
    count: Annotated[int, Query(ge=1)],
    payload: dict,
) -> dict:
    settings = request.app.state.settings
    if count > settings.repeat_max_count:
        raise HTTPException(status_code=400, detail="count exceeds limit")
    if count > settings.ingest_buffer_max_messages:
        raise HTTPException(status_code=429, detail="ingest buffer exceeded")
    producer: SqsFifoIngestProducer = request.app.state.ingest_producer
    body_raw = payload.get("body")
    if not isinstance(body_raw, str):
        raise HTTPException(status_code=400, detail="body must be a string")
    body = _trim_body(body_raw)
    to_val = payload.get("to")
    payload_to = str(to_val) if to_val is not None else None
    now = int(time.time() * 1000)
    batch: list[IngestPutInput] = []
    for _ in range(count):
        mid = str(uuid.uuid4())
        shard = shard_for_message(mid, settings.total_shards)
        batch.append(
            IngestPutInput(
                message_id=mid,
                shard_id=shard,
                payload_body=body,
                payload_to=payload_to,
                received_at_ms=now,
                idempotency_key=mid,
            )
        )
    try:
        await producer.put_messages(batch)
    except IngestUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={"error": "ingest_unavailable", "detail": str(exc)},
        )
    payload = orjson.dumps(
        {
            "accepted": count,
            "messageIds": [b.message_id for b in batch],
            "shardIds": [b.shard_id for b in batch],
        }
    )
    return Response(
        content=payload,
        media_type="application/json",
        status_code=status.HTTP_202_ACCEPTED,
    )


@router.get("/messages/success")
async def get_messages_success(
    request: Request,
    limit: int = Query(default=100, ge=1),
) -> dict:
    settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.http_client
    lim = max(1, min(limit, settings.outcomes_max_limit))
    base = settings.notification_base_url.rstrip("/")
    url = f"{base}/internal/v1/outcomes/success"
    r = await client.get(url, params={"limit": lim})
    r.raise_for_status()
    return r.json()


@router.get("/messages/failed")
async def get_messages_failed(
    request: Request,
    limit: int = Query(default=100, ge=1),
) -> dict:
    settings = request.app.state.settings
    client: httpx.AsyncClient = request.app.state.http_client
    lim = max(1, min(limit, settings.outcomes_max_limit))
    base = settings.notification_base_url.rstrip("/")
    url = f"{base}/internal/v1/outcomes/failed"
    r = await client.get(url, params={"limit": lim})
    r.raise_for_status()
    return r.json()
