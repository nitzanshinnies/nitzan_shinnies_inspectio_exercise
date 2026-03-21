from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from inspectio_exercise.common.health import register_healthz


async def _placeholder_wakeup_loop() -> None:
    """Reserved for 500ms wakeup + due sends (plans/PLAN.md §5)."""
    while True:
        await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_placeholder_wakeup_loop(), name="worker-wakeup-placeholder")
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def create_app() -> FastAPI:
    """HTTP only for probes; scheduler runs as background task (skeleton)."""
    app = FastAPI(
        title="Inspectio Worker",
        version="0.1.0",
        description="Shard-scoped scheduler — see plans/CORE_LIFECYCLE.md; HOSTNAME derives pod index.",
        lifespan=lifespan,
    )
    register_healthz(app, "worker")
    return app


app = create_app()
