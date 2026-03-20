from __future__ import annotations

from fastapi import FastAPI, Response

from inspectio_exercise.common.health import register_healthz


def create_app() -> FastAPI:
    """Persistence microservice: sole S3 I/O boundary for writers (skeleton)."""
    app = FastAPI(
        title="Inspectio Persistence Service",
        version="0.1.0",
        description="Put/get/delete/list-prefix over S3 (or local mock) — see plans/SYSTEM_OVERVIEW.md §1.3.",
    )
    register_healthz(app, "persistence")

    @app.post("/internal/v1/delete-object", tags=["persistence"], status_code=501)
    async def delete_object_stub() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    @app.post("/internal/v1/get-object", tags=["persistence"], status_code=501)
    async def get_object_stub() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    @app.post("/internal/v1/list-prefix", tags=["persistence"], status_code=501)
    async def list_prefix_stub() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    @app.post("/internal/v1/put-object", tags=["persistence"], status_code=501)
    async def put_object_stub() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    @app.get("/internal/v1/ready", tags=["persistence"], include_in_schema=False)
    async def ready() -> Response:
        """Optional readiness hook once S3/backend is wired."""
        return Response(status_code=503)

    return app


app = create_app()
