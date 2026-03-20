from __future__ import annotations

from fastapi import FastAPI

from inspectio_exercise.common.health import register_healthz


def create_app() -> FastAPI:
    """Simulated SMS gateway + audit ring (skeleton)."""
    app = FastAPI(
        title="Inspectio Mock SMS",
        version="0.1.0",
        description="POST /send + audit per plans/MOCK_SMS.md — behavior from mock_sms.config.",
    )
    register_healthz(app, "mock_sms")

    @app.get("/audit/sends", tags=["audit"], status_code=501)
    async def get_audit_sends() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    @app.post("/send", tags=["sms"], status_code=501)
    async def post_send() -> dict[str, str]:
        return {"detail": "not implemented — skeleton only"}

    return app


app = create_app()
