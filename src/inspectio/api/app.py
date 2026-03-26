"""FastAPI factory for inspectio-api (§15 + SQS FIFO producer)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from inspectio.api.routes_public import router
from inspectio.ingest.sqs_fifo_producer import SqsFifoIngestProducer
from inspectio.settings import Settings


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = Settings()
    app.state.settings = settings
    app.state.ingest_producer = SqsFifoIngestProducer(settings)
    async with httpx.AsyncClient() as client:
        app.state.http_client = client
        yield


app = FastAPI(
    title="inspectio-api",
    version="0.0.0",
    lifespan=_lifespan,
)
app.include_router(router)
