from __future__ import annotations

from fastapi import FastAPI

from inspectio_exercise.common.health import register_healthz


def create_app() -> FastAPI:
    """Worker publish + API query for recent outcomes (skeleton)."""
    app = FastAPI(
        title="Inspectio Notification Service",
        version="0.1.0",
        description="Publish terminal outcomes; query Redis — see plans/NOTIFICATION_SERVICE.md.",
    )
    register_healthz(app, "notification")

    @app.get("/internal/v1/outcomes/failed", tags=["internal"], status_code=501)
    async def get_outcomes_failed() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    @app.get("/internal/v1/outcomes/success", tags=["internal"], status_code=501)
    async def get_outcomes_success() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    @app.post("/internal/v1/outcomes", tags=["internal"], status_code=501)
    async def post_outcomes() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    return app


app = create_app()
