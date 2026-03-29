"""Minimal mock SMS HTTP surface (see plans/openapi.yaml mock-sms paths)."""

from __future__ import annotations

import os
import random

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

FAILURE_RATE_ENV = "INSPECTIO_MOCK_FAILURE_RATE"
MOCK_SMS_PORT_DEFAULT = 8080


class MockSmsSendRequest(BaseModel):
    to: str = Field(min_length=1)
    body: str = Field(min_length=1)
    messageId: str | None = None
    attemptIndex: int | None = Field(default=None, ge=0, le=5)


app = FastAPI(title="inspectio-mock-sms", version="0.0.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/send")
def send(payload: MockSmsSendRequest) -> dict[str, str]:
    raw = os.environ.get(FAILURE_RATE_ENV, "0").strip()
    try:
        rate = float(raw)
    except ValueError:
        rate = 0.0
    bounded = max(0.0, min(1.0, rate))
    if bounded > 0.0 and random.random() < bounded:
        raise HTTPException(status_code=500, detail="simulated_provider_failure")
    return {}


def _port() -> int:
    raw = os.environ.get("INSPECTIO_MOCK_SMS_PORT", str(MOCK_SMS_PORT_DEFAULT)).strip()
    try:
        return int(raw)
    except ValueError:
        return MOCK_SMS_PORT_DEFAULT


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=_port())
