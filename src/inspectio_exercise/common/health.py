from __future__ import annotations

from fastapi import FastAPI


def register_healthz(app: FastAPI, service: str) -> None:
    """Register `GET /healthz` liveness (no dependency checks)."""

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": service}
