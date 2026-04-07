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
from inspectio.v3.persistence_emitter.enqueued_outbound import (
    L2EnqueuedPersistenceOutboundQueue,
)
from inspectio.v3.persistence_emitter.noop import NoopPersistenceEventEmitter
from inspectio.v3.persistence_emitter.transport import TransportPersistenceEventEmitter
from inspectio.v3.persistence_transport.sharded_router import (
    ShardedPersistenceTransportProducer,
)
from inspectio.v3.persistence_transport.sqs_producer import (
    SqsPersistenceTransportProducer,
)
from inspectio.v3.schemas.bulk_intent import BulkIntentV1
from inspectio.v3.settings import V3PersistenceSettings, V3SqsSettings
from inspectio.v3.sqs.boto_config import augment_client_kwargs_with_v3_config
from inspectio.v3.sqs.bulk_producer import SqsBulkEnqueue


class _EnqueueRelay:
    """Bound after lifespan starts so ``SqsBulkEnqueue`` can reuse one SQS client."""

    impl: SqsBulkEnqueue | None = None

    async def enqueue(self, bulk: BulkIntentV1) -> None:
        if self.impl is None:
            msg = "L2 enqueue used before application lifespan started"
            raise RuntimeError(msg)
        await self.impl.enqueue(bulk)


class _PersistenceEmitterRelay:
    """Bound after lifespan starts; defaults to no-op before binding."""

    def __init__(self) -> None:
        self.impl = NoopPersistenceEventEmitter()

    async def emit_enqueued(self, **kwargs: object) -> None:
        await self.impl.emit_enqueued(**kwargs)

    async def emit_attempt_result(self, **kwargs: object) -> None:
        await self.impl.emit_attempt_result(**kwargs)

    async def emit_terminal(self, **kwargs: object) -> None:
        await self.impl.emit_terminal(**kwargs)

    async def persistence_transport_observability_snapshot(
        self,
    ) -> dict[str, object] | None:
        impl = self.impl
        if isinstance(impl, TransportPersistenceEventEmitter):
            return await impl.persistence_transport_observability_snapshot()
        return None


def create_l2_app_from_env() -> FastAPI:
    """SQS bulk enqueue + optional Redis outcomes (else empty GET lists)."""
    relay = _EnqueueRelay()
    emitter_relay = _PersistenceEmitterRelay()
    shard_count = int(os.environ.get("INSPECTIO_V3_SEND_SHARD_COUNT", "1"))
    redis_url = os.environ.get("INSPECTIO_REDIS_URL") or os.environ.get("REDIS_URL")
    persistence_settings = V3PersistenceSettings()
    outcomes_reader = (
        RedisOutcomesStore.from_url(redis_url) if redis_url else NullOutcomesReader()
    )
    if (
        persistence_settings.persistence_emit_enabled
        and persistence_settings.persist_transport_queue_urls
    ):
        persistence_transport_shard_count = len(
            persistence_settings.persist_transport_queue_urls
        )
    else:
        persistence_transport_shard_count = 1

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
        sqs_kw = augment_client_kwargs_with_v3_config(client_kw)
        enqueued_outbound: L2EnqueuedPersistenceOutboundQueue | None = None
        async with session.client("sqs", **sqs_kw) as client:
            relay.impl = SqsBulkEnqueue(
                queue_url=settings.bulk_queue_url,
                region_name=settings.aws_region,
                endpoint_url=settings.aws_endpoint_url,
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                session=session,
                bound_client=client,
            )
            if persistence_settings.persistence_emit_enabled:
                if persistence_settings.persist_transport_queue_urls:
                    producers_by_shard: dict[int, SqsPersistenceTransportProducer] = {}
                    for shard_id, queue_url in enumerate(
                        persistence_settings.persist_transport_queue_urls
                    ):
                        dlq_url = None
                        if persistence_settings.persist_transport_dlq_urls:
                            dlq_url = persistence_settings.persist_transport_dlq_urls[
                                shard_id
                            ]
                        producers_by_shard[shard_id] = SqsPersistenceTransportProducer(
                            queue_url=queue_url,
                            dlq_queue_url=dlq_url,
                            client=client,
                            durability_mode=persistence_settings.persistence_durability_mode,
                            max_attempts=persistence_settings.persist_transport_max_attempts,
                            backoff_base_ms=persistence_settings.persist_transport_backoff_base_ms,
                            backoff_max_ms=persistence_settings.persist_transport_backoff_max_ms,
                            backoff_jitter_fraction=persistence_settings.persist_transport_backoff_jitter_fraction,
                            max_inflight_events=persistence_settings.persist_transport_max_inflight_events,
                            max_batch_events=persistence_settings.persist_transport_batch_max_events,
                        )
                    producer = ShardedPersistenceTransportProducer(
                        producers_by_shard=producers_by_shard
                    )
                else:
                    producer = SqsPersistenceTransportProducer(
                        queue_url=str(persistence_settings.persist_transport_queue_url),
                        dlq_queue_url=persistence_settings.persist_transport_dlq_url,
                        client=client,
                        durability_mode=persistence_settings.persistence_durability_mode,
                        max_attempts=persistence_settings.persist_transport_max_attempts,
                        backoff_base_ms=persistence_settings.persist_transport_backoff_base_ms,
                        backoff_max_ms=persistence_settings.persist_transport_backoff_max_ms,
                        backoff_jitter_fraction=persistence_settings.persist_transport_backoff_jitter_fraction,
                        max_inflight_events=persistence_settings.persist_transport_max_inflight_events,
                        max_batch_events=persistence_settings.persist_transport_batch_max_events,
                    )
                enqueued_outbound = L2EnqueuedPersistenceOutboundQueue(
                    producer=producer,
                )
                enqueued_outbound.start()
                emitter_relay.impl = TransportPersistenceEventEmitter(
                    producer=producer,
                    clock_ms=lambda: int(time.time() * 1000),
                    enqueued_outbound=enqueued_outbound,
                )
            try:
                yield
            finally:
                if enqueued_outbound is not None:
                    await enqueued_outbound.stop()

    return create_l2_app(
        enqueue_backend=relay,
        clock_ms=lambda: int(time.time() * 1000),
        shard_count=shard_count,
        outcomes_reader=outcomes_reader,
        persistence_emitter=emitter_relay,
        persistence_transport_shard_count=persistence_transport_shard_count,
        expose_persistence_transport_metrics=persistence_settings.expose_persistence_transport_metrics,
        lifespan=lifespan,
    )
