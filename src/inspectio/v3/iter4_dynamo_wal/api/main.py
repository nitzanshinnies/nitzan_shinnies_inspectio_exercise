"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
import uvicorn

from inspectio.v3.iter4_dynamo_wal.aws_clients import (
    aioboto3_session,
    botocore_high_throughput_config,
    session_kwargs,
)
from inspectio.v3.iter4_dynamo_wal.config import (
    Iter4DynamoWalSettings,
    iter4_settings_from_env,
)
from inspectio.v3.iter4_dynamo_wal.message_repository import MessageRepository
from inspectio.v3.iter4_dynamo_wal.models import NewMessageRequest, NewMessageResponse
from inspectio.v3.iter4_dynamo_wal.new_message_service import handle_new_message
from inspectio.v3.iter4_dynamo_wal.sender import MockSmsSender, SmsSender
from inspectio.v3.iter4_dynamo_wal.wal_buffer import WalBuffer


def create_iter4_app(
    *,
    settings: Iter4DynamoWalSettings | None = None,
    sender: SmsSender | None = None,
) -> FastAPI:
    settings = settings or iter4_settings_from_env()
    sender = sender or MockSmsSender()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        session = aioboto3_session()
        config = botocore_high_throughput_config()
        base_kw = session_kwargs(
            region_name=settings.aws_region,
            endpoint_url=settings.aws_endpoint_url,
        )
        if not settings.s3_bucket:
            raise RuntimeError("INSPECTIO_V3_ITER4_S3_BUCKET is required for API WAL")

        async with session.client("dynamodb", config=config, **base_kw) as ddb_client:
            async with session.client("s3", config=config, **base_kw) as s3_client:
                wal = WalBuffer(
                    writer_id=settings.wal_writer_id,
                    bucket=settings.s3_bucket,
                    wal_prefix=settings.s3_wal_prefix,
                )
                wal.attach_s3_client(s3_client)
                wal.start_background()
                repo = MessageRepository(
                    client=ddb_client,
                    table_name=settings.dynamodb_table_name,
                    gsi_scheduling_index_name=settings.gsi_scheduling_index_name,
                )
                app.state.settings = settings
                app.state.repo = repo
                app.state.sender = sender
                app.state.wal = wal
                try:
                    yield
                finally:
                    await wal.stop()

    app = FastAPI(
        title="Inspectio v3 Iter4 — DynamoDB + S3 WAL scheduler API",
        lifespan=lifespan,
    )

    def get_repo(request: Request) -> MessageRepository:
        return request.app.state.repo

    def get_wal(request: Request) -> WalBuffer:
        return request.app.state.wal

    def get_sender_dep(request: Request) -> SmsSender:
        return request.app.state.sender

    def get_settings_dep(request: Request) -> Iter4DynamoWalSettings:
        return request.app.state.settings

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/messages", response_model=NewMessageResponse)
    async def new_message(
        body: NewMessageRequest,
        repo: MessageRepository = Depends(get_repo),
        wal: WalBuffer = Depends(get_wal),
        sender_dep: SmsSender = Depends(get_sender_dep),
        st: Iter4DynamoWalSettings = Depends(get_settings_dep),
    ) -> NewMessageResponse:
        return await handle_new_message(
            message_id=body.message_id,
            payload=body.payload,
            repo=repo,
            sender=sender_dep,
            wal=wal,
            total_shards=st.total_shards,
        )

    return app


app = create_iter4_app()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "inspectio.v3.iter4_dynamo_wal.api.main:app",
        host="0.0.0.0",
        port=8000,
        factory=False,
    )


if __name__ == "__main__":
    run()
