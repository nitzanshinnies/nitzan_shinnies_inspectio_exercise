from __future__ import annotations

from fastapi import FastAPI

from inspectio_exercise.common.health import register_healthz


def create_app() -> FastAPI:
    """Read-only reconciliation vs mock + S3 (skeleton)."""
    app = FastAPI(
        title="Inspectio Health Monitor",
        version="0.1.0",
        description="GET /healthz liveness only; expensive work on POST integrity-check — plans/HEALTH_MONITOR.md.",
    )
    register_healthz(app, "health_monitor")

    @app.post("/internal/v1/integrity-check", tags=["internal"], status_code=501)
    async def post_integrity_check() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    return app


app = create_app()
