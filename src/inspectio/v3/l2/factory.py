"""Construct L2 from environment (docker / local dev)."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aioboto3
from fastapi import FastAPI

from inspectio.v3.l2.app import create_l2_app
from inspectio.v3.outcomes.null_store import NullOutcomesReader
from inspectio.v3.outcomes.redis_store import RedisOutcomesStore
from inspectio.v3.schemas.bulk_intent import BulkIntentV1
from inspectio.v3.settings import V3SqsSettings
from inspectio.v3.sqs.bulk_producer import SqsBulkEnqueue


class _EnqueueRelay:
    """Bound after lifespan starts so ``SqsBulkEnqueue`` can reuse one SQS client."""

    impl: SqsBulkEnqueue | None = None

    async def enqueue(self, bulk: BulkIntentV1) -> None:
        if self.impl is None:
            msg = "L2 enqueue used before application lifespan started"
            raise RuntimeError(msg)
        await self.impl.enqueue(bulk)


def create_l2_app_from_env() -> FastAPI:
    """SQS bulk enqueue + optional Redis outcomes (else empty GET lists)."""
    relay = _EnqueueRelay()
    shard_count = int(os.environ.get("INSPECTIO_V3_SEND_SHARD_COUNT", "1"))
    redis_url = os.environ.get("INSPECTIO_REDIS_URL") or os.environ.get("REDIS_URL")
    outcomes_reader = (
        RedisOutcomesStore.from_url(redis_url) if redis_url else NullOutcomesReader()
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        settings = V3SqsSettings()
        session = aioboto3.Session()
        client_kw: dict[str, str] = {"region_name": settings.aws_region}
        if settings.aws_endpoint_url:
            client_kw["endpoint_url"] = settings.aws_endpoint_url
        if settings.aws_access_key_id:
            client_kw["aws_access_key_id"] = settings.aws_access_key_id
        if settings.aws_secret_access_key:
            client_kw["aws_secret_access_key"] = settings.aws_secret_access_key
        async with session.client("sqs", **client_kw) as client:
            relay.impl = SqsBulkEnqueue(
                queue_url=settings.bulk_queue_url,
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                session=session,
                bound_client=client,
            )
            yield

    return create_l2_app(
        enqueue_backend=relay,
        clock_ms=lambda: int(time.time() * 1000),
        shard_count=shard_count,
        outcomes_reader=outcomes_reader,
        lifespan=lifespan,
    )
