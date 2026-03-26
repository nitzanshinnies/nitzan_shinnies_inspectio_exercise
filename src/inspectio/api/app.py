"""FastAPI application factory for inspectio public API."""

from __future__ import annotations

from fastapi import FastAPI

from inspectio.api.routes_public import NotificationClient, router as public_router
from inspectio.ingest.kinesis_producer import SqsFifoIngestProducer
from inspectio.settings import get_settings


def create_app() -> FastAPI:
    """Create and wire API dependencies for runtime and tests."""
    app = FastAPI(title="inspectio-api", version="0.0.0")
    settings = get_settings()
    app.state.settings = settings
    app.state.ingest_producer = SqsFifoIngestProducer(settings)
    app.state.notification_client = NotificationClient(
        base_url=settings.inspectio_notification_base_url
    )
    app.include_router(public_router)
    return app


app = create_app()
