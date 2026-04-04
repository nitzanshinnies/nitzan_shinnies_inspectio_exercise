"""P3: publish groups by shard and calls SendMessageBatch (mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from inspectio.v3.expander.metrics import ExpansionMetrics
from inspectio.v3.expander.publish import publish_send_units_to_shards
from inspectio.v3.schemas.bulk_intent import BulkIntentV1
from inspectio.v3.schemas.send_unit import SendUnitV1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_publish_batches_per_shard() -> None:
    bulk = BulkIntentV1(
        trace_id="t",
        batch_correlation_id="11111111-1111-4111-8111-111111111111",
        idempotency_key="i",
        count=1,
        body="x",
        received_at_ms=0,
    )
    u0 = SendUnitV1(
        trace_id=bulk.trace_id,
        message_id="m0",
        body=bulk.body,
        received_at_ms=bulk.received_at_ms,
        batch_correlation_id=bulk.batch_correlation_id,
        shard=0,
    )
    u1 = SendUnitV1(
        trace_id=bulk.trace_id,
        message_id="m1",
        body=bulk.body,
        received_at_ms=bulk.received_at_ms,
        batch_correlation_id=bulk.batch_correlation_id,
        shard=1,
    )
    client = AsyncMock()
    client.send_message_batch = AsyncMock(
        return_value={"Successful": [{"Id": "x"}], "Failed": []}
    )
    metrics = ExpansionMetrics()
    sleeper = AsyncMock()
    await publish_send_units_to_shards(
        client,
        units=[u0, u1],
        send_queue_urls=["http://q0", "http://q1"],
        max_attempts=3,
        sleeper=sleeper,
        rng=__import__("random").Random(0),
        metrics=metrics,
    )
    assert client.send_message_batch.await_count == 2
    urls = {c.kwargs["QueueUrl"] for c in client.send_message_batch.await_args_list}
    assert urls == {"http://q0", "http://q1"}
    assert metrics.expanded_units_published == 2
