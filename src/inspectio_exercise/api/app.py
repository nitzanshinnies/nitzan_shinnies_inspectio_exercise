"""Public REST API — skeleton routes only (plans/REST_API.md).

TDD: implement validation + handlers in a follow-up; `tests/unit/test_rest_handlers.py` is the contract.
"""

from __future__ import annotations

from fastapi import FastAPI

from inspectio_exercise.common.health import register_healthz


def create_app() -> FastAPI:
    """Architect REST surface — outcomes delegated to notification service (skeleton)."""
    app = FastAPI(
        title="Inspectio REST API",
        version="0.1.0",
        description="Public API per plans/REST_API.md — persistence via persistence service only.",
    )
    register_healthz(app, "api")

    @app.get("/messages/failed", tags=["messages"], status_code=501)
    async def get_messages_failed() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    @app.get("/messages/success", tags=["messages"], status_code=501)
    async def get_messages_success() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    @app.post("/messages", tags=["messages"], status_code=501)
    async def post_messages() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    @app.post("/messages/repeat", tags=["messages"], status_code=501)
    async def post_messages_repeat() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    return app


app = create_app()
