from __future__ import annotations

import asyncio

import pytest

import inspectio_exercise.api.config as api_config
from inspectio_exercise.api.use_cases import submit_messages_repeat_parallel


class _UnusedPersistence:
    async def put_objects(self, items):  # pragma: no cover - explicit fallback only
        del items


@pytest.mark.asyncio
@pytest.mark.unit
async def test_repeat_submit_respects_max_concurrent_put_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_config, "REPEAT_SUBMIT_PUT_BATCH_SIZE", 2)
    monkeypatch.setattr(api_config, "REPEAT_SUBMIT_PUT_MAX_CONCURRENCY", 3)

    active_writers = 0
    max_active_writers = 0
    lock = asyncio.Lock()

    async def persist_pending_batch(items) -> None:
        nonlocal active_writers, max_active_writers
        assert len(items) <= 2
        async with lock:
            active_writers += 1
            max_active_writers = max(max_active_writers, active_writers)
        await asyncio.sleep(0.01)
        async with lock:
            active_writers -= 1

    ids = await submit_messages_repeat_parallel(
        _UnusedPersistence(),
        body="load-test",
        count=10,
        should_fail=False,
        to="+15550000000",
        total_shards=256,
        worker_clients=[],
        shards_per_pod=256,
        persist_pending_batch=persist_pending_batch,
    )

    assert len(ids) == 10
    assert len(set(ids)) == 10
    assert 1 < max_active_writers <= api_config.REPEAT_SUBMIT_PUT_MAX_CONCURRENCY
