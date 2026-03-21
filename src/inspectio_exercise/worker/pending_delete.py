"""Best-effort removal of a pending key (swallow missing object)."""

from __future__ import annotations

import contextlib

from inspectio_exercise.worker.retrying_persistence import RetryingPersistence


async def delete_pending_best_effort(persist: RetryingPersistence, key: str) -> None:
    with contextlib.suppress(KeyError):
        await persist.delete_object(key)
