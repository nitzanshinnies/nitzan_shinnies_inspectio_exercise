"""P4: Redis outcomes LPUSH/LTRIM + list (opt-in)."""

from __future__ import annotations

import os

import pytest
import redis.asyncio as redis_async

from inspectio.v3.outcomes.redis_store import RedisOutcomesStore


def _enabled() -> bool:
    return os.environ.get("INSPECTIO_REDIS_INTEGRATION") == "1"


pytestmark = pytest.mark.skipif(
    not _enabled(),
    reason="Set INSPECTIO_REDIS_INTEGRATION=1 and REDIS_URL (see README P4)",
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_record_success_then_list_newest_first() -> None:
    url = os.environ.get("REDIS_URL") or os.environ.get(
        "INSPECTIO_REDIS_URL",
        "redis://127.0.0.1:6379/15",
    )
    flush_client = redis_async.from_url(url, decode_responses=True)
    await flush_client.flushdb()
    await flush_client.aclose()
    store = RedisOutcomesStore.from_url(url)
    try:
        await store.record_success(
            message_id="older",
            attempt_count=1,
            final_timestamp_ms=100,
        )
        await store.record_success(
            message_id="newer",
            attempt_count=2,
            final_timestamp_ms=200,
        )
        items = await store.list_success(limit=10)
        assert [x["messageId"] for x in items] == ["newer", "older"]
    finally:
        await store.aclose()
