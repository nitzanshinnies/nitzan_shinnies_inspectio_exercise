"""Unit tests for SQS FIFO producer (SQS-P1 parallel cross-group batches)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from inspectio.ingest.ingest_producer import IngestPutInput
from inspectio.ingest.sqs_fifo_producer import (
    MAX_SQS_FIFO_SEND_BATCH,
    SqsFifoIngestProducer,
)
from inspectio.settings import Settings


def _msg(i: int, shard: int) -> IngestPutInput:
    return IngestPutInput(
        message_id=f"m{i}",
        shard_id=shard,
        payload_body="x",
        payload_to=None,
        received_at_ms=1,
        idempotency_key=f"m{i}",
    )


def _success_batch(n: int) -> dict:
    return {
        "Successful": [{"Id": str(i), "MessageId": f"sqs-{i}"} for i in range(n)],
        "Failed": [],
    }


@pytest.mark.asyncio
async def test_put_messages_empty_returns_empty() -> None:
    settings = Settings(ingest_queue_url="https://sqs.example/queue.fifo")
    producer = SqsFifoIngestProducer(settings)
    out = await producer.put_messages([])
    assert out == []


@pytest.mark.asyncio
async def test_put_messages_preserves_order_across_shards() -> None:
    """Interleaved shard ids must return results in original message order."""
    settings = Settings(ingest_queue_url="https://sqs.example/queue.fifo")
    producer = SqsFifoIngestProducer(settings)
    messages = [_msg(0, 0), _msg(1, 1), _msg(2, 0), _msg(3, 2)]
    mock_client = AsyncMock()

    async def send_batch2(*_a: object, **kwargs: object) -> dict:
        entries = kwargs.get("Entries", [])
        n = len(entries)
        return _success_batch(n)

    mock_client.send_message_batch = AsyncMock(side_effect=send_batch2)
    session = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    session.client = MagicMock(return_value=cm)

    with patch(
        "inspectio.ingest.sqs_fifo_producer.aioboto3.Session", return_value=session
    ):
        out = await producer.put_messages(messages)

    assert [r.message_id for r in out] == ["m0", "m1", "m2", "m3"]
    # Shards 0,1,2 → 3 groups; batches: 2+1+1 messages
    assert mock_client.send_message_batch.await_count == 3


@pytest.mark.asyncio
async def test_single_group_large_repeat_uses_multiple_sequential_batches() -> None:
    """One MessageGroupId: multiple SendMessageBatch calls, chunk size 10."""
    settings = Settings(ingest_queue_url="https://sqs.example/queue.fifo")
    producer = SqsFifoIngestProducer(settings)
    n = 25
    messages = [_msg(i, 7) for i in range(n)]
    mock_client = AsyncMock()
    mock_client.send_message_batch = AsyncMock(
        side_effect=[_success_batch(10), _success_batch(10), _success_batch(5)]
    )
    session = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    session.client = MagicMock(return_value=cm)

    with patch(
        "inspectio.ingest.sqs_fifo_producer.aioboto3.Session", return_value=session
    ):
        await producer.put_messages(messages)

    assert mock_client.send_message_batch.await_count == 3
    for c in mock_client.send_message_batch.call_args_list:
        entries = c.kwargs["Entries"]
        assert len(entries) <= MAX_SQS_FIFO_SEND_BATCH


@pytest.mark.asyncio
async def test_parallel_groups_limited_by_semaphore() -> None:
    """Two groups run as separate tasks; semaphore allows up to max_groups concurrent group pipelines."""
    settings = Settings(
        ingest_queue_url="https://sqs.example/queue.fifo",
        max_sqs_fifo_inflight_groups=2,
    )
    producer = SqsFifoIngestProducer(settings)
    messages = [_msg(0, 0), _msg(1, 1)]
    mock_client = AsyncMock()
    mock_client.send_message_batch = AsyncMock(return_value=_success_batch(1))
    session = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    session.client = MagicMock(return_value=cm)

    with patch(
        "inspectio.ingest.sqs_fifo_producer.aioboto3.Session", return_value=session
    ):
        await producer.put_messages(messages)

    assert mock_client.send_message_batch.await_count == 2


@pytest.mark.unit
def test_partition_key_for_shard_fixed_width() -> None:
    from inspectio.ingest.ingest_producer import partition_key_for_shard

    assert partition_key_for_shard(0) == "00000"
    assert partition_key_for_shard(42) == "00042"
