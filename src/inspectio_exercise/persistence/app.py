"""Persistence microservice — HTTP surface over ``PersistencePort`` (local files or AWS S3)."""

from __future__ import annotations

import base64
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response

from inspectio_exercise.common.health import register_healthz
from inspectio_exercise.persistence.backend import build_persistence_backend
from inspectio_exercise.persistence.interface import PersistencePort
from inspectio_exercise.persistence.schemas import (
    DeleteObjectRequest,
    GetObjectRequest,
    GetObjectResponse,
    ListPrefixRequest,
    ListPrefixResponse,
    PutObjectRequest,
)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    app.state.backend = build_persistence_backend()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Inspectio Persistence Service",
        version="0.1.0",
        description="Put/get/delete/list-prefix — local file tree or AWS S3 (plans/SYSTEM_OVERVIEW.md §1.3).",
        lifespan=_lifespan,
    )
    register_healthz(app, "persistence")

    def require_backend(request: Request) -> PersistencePort:
        backend = getattr(request.app.state, "backend", None)
        if backend is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "persistence backend not configured — set INSPECTIO_PERSISTENCE_BACKEND=local "
                    "with LOCAL_S3_ROOT, or INSPECTIO_PERSISTENCE_BACKEND=aws with "
                    "INSPECTIO_S3_BUCKET (or S3_BUCKET); implicit mode uses LOCAL_S3_ROOT for "
                    "local or bucket env vars for AWS"
                ),
            )
        return backend

    @app.post("/internal/v1/delete-object", tags=["persistence"])
    async def delete_object(
        body: DeleteObjectRequest,
        backend: PersistencePort = Depends(require_backend),
    ) -> dict[str, str]:
        await backend.delete_object(body.key)
        return {"status": "ok"}

    @app.post("/internal/v1/get-object", tags=["persistence"])
    async def get_object(
        body: GetObjectRequest,
        backend: PersistencePort = Depends(require_backend),
    ) -> GetObjectResponse:
        try:
            raw = await backend.get_object(body.key)
        except KeyError:
            raise HTTPException(
                status_code=404, detail={"key": body.key, "reason": "not found"}
            ) from None
        return GetObjectResponse(body_b64=base64.b64encode(raw).decode("ascii"))

    @app.post("/internal/v1/list-prefix", tags=["persistence"])
    async def list_prefix(
        body: ListPrefixRequest,
        backend: PersistencePort = Depends(require_backend),
    ) -> ListPrefixResponse:
        rows = await backend.list_prefix(body.prefix, max_keys=body.max_keys)
        return ListPrefixResponse(keys=rows)

    @app.post("/internal/v1/put-object", tags=["persistence"])
    async def put_object(
        body: PutObjectRequest,
        backend: PersistencePort = Depends(require_backend),
    ) -> dict[str, str]:
        raw = base64.b64decode(body.body_b64)
        await backend.put_object(body.key, raw, content_type=body.content_type)
        return {"status": "ok"}

    @app.get("/internal/v1/ready", tags=["persistence"], include_in_schema=False)
    async def ready(request: Request) -> Response:
        backend = getattr(request.app.state, "backend", None)
        if backend is None:
            return Response(status_code=503)
        return Response(status_code=200)

    return app


app = create_app()
