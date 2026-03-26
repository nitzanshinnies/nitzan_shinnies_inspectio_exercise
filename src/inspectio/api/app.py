"""FastAPI application factory for inspectio public API."""

from __future__ import annotations

from fastapi import FastAPI

from inspectio.api.routes_public import router as public_router
from inspectio.ingest.kinesis_producer import KinesisIngestProducer
from inspectio.settings import get_settings


def create_app() -> FastAPI:
    """Create and wire API dependencies for runtime and tests."""
    app = FastAPI(title="inspectio-api", version="0.0.0")
    settings = get_settings()
    app.state.settings = settings
    app.state.kinesis_producer = KinesisIngestProducer(settings)
    app.include_router(public_router)
    return app


app = create_app()
