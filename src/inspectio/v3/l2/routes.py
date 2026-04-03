"""FastAPI routes for v3 L2 admission (P1)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError

from inspectio.v3.l2.deps import L2Dependencies
from inspectio.v3.l2.fingerprint import admission_fingerprint
from inspectio.v3.l2.http_models import PostMessageRequestBody
from inspectio.v3.l2.idempotency import IdempotencyConflictError
from inspectio.v3.l2.sharding import predicted_shard_index
from inspectio.v3.schemas.bulk_intent import BulkIntentV1


def build_router(deps: L2Dependencies) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "api"}

    @router.get("/messages/success")
    async def messages_success(
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
    ) -> dict[str, Any]:
        items = await deps.outcomes_reader.list_success(limit=limit)
        return {"items": items}

    @router.get("/messages/failed")
    async def messages_failed(
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
    ) -> dict[str, Any]:
        items = await deps.outcomes_reader.list_failed(limit=limit)
        return {"items": items}

    @router.post("/messages", status_code=202)
    async def post_messages(
        payload: PostMessageRequestBody,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
    ) -> dict[str, str | int]:
        return await _admit_bulk(
            deps=deps,
            body=payload.body,
            to=payload.to,
            count=1,
            idempotency_key=idempotency_key,
            trace_id=trace_id or str(uuid.uuid4()),
        )

    @router.post("/messages/repeat", status_code=202)
    async def post_messages_repeat(
        count: Annotated[int, Query(ge=1, le=100_000)],
        payload: PostMessageRequestBody,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
    ) -> dict[str, str | int]:
        return await _admit_bulk(
            deps=deps,
            body=payload.body,
            to=payload.to,
            count=count,
            idempotency_key=idempotency_key,
            trace_id=trace_id or str(uuid.uuid4()),
        )

    return router


async def _admit_bulk(
    *,
    deps: L2Dependencies,
    body: str,
    to: str | None,
    count: int,
    idempotency_key: str | None,
    trace_id: str,
) -> dict[str, str | int]:
    fingerprint = admission_fingerprint(body=body, to=to, count=count)
    new_batch_id = str(uuid.uuid4())
    try:
        if idempotency_key is not None and idempotency_key.strip() != "":
            batch_id, duplicate = deps.idempotency.resolve(
                idempotency_key.strip(),
                fingerprint,
                new_batch_id,
            )
        else:
            batch_id, duplicate = new_batch_id, False
    except IdempotencyConflictError:
        raise HTTPException(
            status_code=409, detail="idempotency_key_conflict"
        ) from None

    if duplicate:
        return _response_for_admission(
            batch_id=batch_id,
            count=count,
            shard_count=deps.shard_count,
        )

    metadata: dict[str, str] | None = {"to": to} if to else None
    idem_for_envelope = (
        idempotency_key.strip()
        if idempotency_key and idempotency_key.strip()
        else batch_id
    )
    received_at_ms = deps.clock_ms()
    shard = predicted_shard_index(
        batch_correlation_id=batch_id,
        shard_count=deps.shard_count,
    )
    bulk = BulkIntentV1(
        trace_id=trace_id,
        batch_correlation_id=batch_id,
        idempotency_key=idem_for_envelope,
        count=count,
        body=body,
        received_at_ms=received_at_ms,
        metadata=metadata,
    )
    await deps.enqueue_backend.enqueue(bulk)
    await deps.persistence_emitter.emit_enqueued(
        trace_id=trace_id,
        batch_correlation_id=batch_id,
        idempotency_key=idem_for_envelope,
        count=count,
        body=body,
        received_at_ms=received_at_ms,
        shard=shard,
    )
    return _response_for_admission(
        batch_id=batch_id,
        count=count,
        shard_count=deps.shard_count,
    )


def _response_for_admission(
    *,
    batch_id: str,
    count: int,
    shard_count: int,
) -> dict[str, str | int]:
    shard = predicted_shard_index(
        batch_correlation_id=batch_id, shard_count=shard_count
    )
    if count == 1:
        return {
            "messageId": batch_id,
            "batchCorrelationId": batch_id,
            "shardId": shard,
        }
    return {
        "accepted": count,
        "batchCorrelationId": batch_id,
        "count": count,
    }


async def validation_exception_handler(
    request: object, exc: RequestValidationError
) -> object:
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=400, content={"detail": jsonable_encoder(exc.errors())}
    )
