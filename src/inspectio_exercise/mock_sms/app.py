from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from inspectio_exercise.common.health import register_healthz
from inspectio_exercise.mock_sms import config
from inspectio_exercise.mock_sms.audit import recent_audit_rows
from inspectio_exercise.mock_sms.send_handler import handle_send_request


class SendRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    attempt_index: int | None = Field(default=None, alias="attemptIndex")
    body: str | None = None
    message_id: str | None = Field(default=None, alias="messageId")
    should_fail: bool = Field(default=False, alias="shouldFail")
    to: str | None = None


def create_app() -> FastAPI:
    """Simulated SMS gateway + audit ring (plans/MOCK_SMS.md)."""
    app = FastAPI(
        title="Inspectio Mock SMS",
        version="0.1.0",
        description="POST /send + audit per plans/MOCK_SMS.md — behavior from mock_sms.config.",
    )
    register_healthz(app, "mock_sms")

    @app.get("/audit/sends", tags=["audit"])
    async def get_audit_sends(limit: int = config.AUDIT_SENDS_DEFAULT_LIMIT) -> list[dict]:
        if not config.EXPOSE_AUDIT_ENDPOINT:
            raise HTTPException(status_code=404, detail="audit endpoint disabled")
        if limit < 1:
            raise HTTPException(status_code=422, detail="limit must be >= 1")
        cap = min(limit, config.AUDIT_SENDS_MAX_LIMIT)
        return recent_audit_rows(cap)

    @app.post("/send", tags=["sms"])
    async def post_send(body: SendRequest) -> JSONResponse:
        status, payload = await handle_send_request(body.model_dump(by_alias=True))
        return JSONResponse(status_code=status, content=payload)

    return app


app = create_app()
