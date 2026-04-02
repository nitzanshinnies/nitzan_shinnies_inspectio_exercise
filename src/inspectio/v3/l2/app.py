"""FastAPI L2 application factory (P1)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from inspectio.v3.l2.deps import L2Dependencies
from inspectio.v3.l2.enqueue_port import BulkEnqueuePort
from inspectio.v3.l2.idempotency import InMemoryIdempotencyStore
from inspectio.v3.l2.routes import build_router, validation_exception_handler
from inspectio.v3.outcomes.null_store import NullOutcomesReader
from inspectio.v3.outcomes.protocol import OutcomesReadPort
from inspectio.v3.persistence_emitter.noop import NoopPersistenceEventEmitter
from inspectio.v3.persistence_emitter.protocol import PersistenceEventEmitter


def create_l2_app(
    *,
    enqueue_backend: BulkEnqueuePort,
    clock_ms: Callable[[], int],
    shard_count: int = 1,
    idempotency_ttl_ms: int = 3_600_000,
    outcomes_reader: OutcomesReadPort | None = None,
    persistence_emitter: PersistenceEventEmitter | None = None,
    lifespan: Callable[[FastAPI], AsyncIterator[None]] | None = None,
) -> FastAPI:
    """Build L2 with injectable clock and enqueue; idempotency is in-process only (P1)."""
    idempotency = InMemoryIdempotencyStore(ttl_ms=idempotency_ttl_ms, clock_ms=clock_ms)
    reader = outcomes_reader or NullOutcomesReader()
    emitter = persistence_emitter or NoopPersistenceEventEmitter()
    deps = L2Dependencies(
        clock_ms=clock_ms,
        enqueue_backend=enqueue_backend,
        idempotency=idempotency,
        outcomes_reader=reader,
        persistence_emitter=emitter,
        shard_count=shard_count,
    )
    kwargs: dict[str, object] = {"title": "Inspectio L2", "version": "0.0.0"}
    if lifespan is not None:
        kwargs["lifespan"] = lifespan
    app = FastAPI(**kwargs)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.include_router(build_router(deps))
    return app
