"""P2: SqsBulkEnqueue throttling retries (mocked aioboto3)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from inspectio.v3.schemas.bulk_intent import BulkIntentV1
from inspectio.v3.sqs.bulk_producer import SqsBulkEnqueue


def _fake_session(sqs_client: Any) -> MagicMock:
    session = MagicMock()

    async def _aenter() -> Any:
        return sqs_client

    async def _aexit__(*_a: object) -> None:
        return None

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(side_effect=_aenter)
    cm.__aexit__ = AsyncMock(side_effect=_aexit__)
    session.client = MagicMock(return_value=cm)
    return session


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_sends_json_body() -> None:
    sqs = AsyncMock()
    sqs.send_message = AsyncMock(return_value={"MessageId": "mid"})
    producer = SqsBulkEnqueue(
        queue_url="https://sqs.us-east-1.amazonaws.com/1/q",
        region_name="us-east-1",
        endpoint_url=None,
        max_attempts=3,
        sleeper=AsyncMock(),
        session=_fake_session(sqs),
    )
    bulk = BulkIntentV1(
        trace_id="t",
        batch_correlation_id="b1111111-1111-4111-8111-111111111111",
        idempotency_key="i",
        count=2,
        body="hello",
        received_at_ms=1,
    )
    await producer.enqueue(bulk)
    sqs.send_message.assert_awaited_once()
    call_kw = sqs.send_message.await_args.kwargs
    assert call_kw["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/1/q"
    body = call_kw["MessageBody"]
    assert "schemaVersion" in body and "traceId" in body
    assert '"count": 2' in body or '"count":2' in body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_retries_throttling_then_succeeds() -> None:
    throttle = ClientError(
        {
            "Error": {"Code": "Throttling", "Message": "slow down"},
            "ResponseMetadata": {},
        },
        "SendMessage",
    )
    sqs = AsyncMock()
    sqs.send_message = AsyncMock(side_effect=[throttle, throttle, {"MessageId": "ok"}])
    sleeper = AsyncMock()
    producer = SqsBulkEnqueue(
        queue_url="https://example/q",
        region_name="us-east-1",
        endpoint_url="http://localhost:4566",
        max_attempts=5,
        sleeper=sleeper,
        session=_fake_session(sqs),
    )
    bulk = BulkIntentV1(
        trace_id="t",
        batch_correlation_id="b2222222-2222-4222-8222-222222222222",
        idempotency_key="i",
        count=1,
        body="x",
        received_at_ms=0,
    )
    await producer.enqueue(bulk)
    assert sqs.send_message.await_count == 3
    assert sleeper.await_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_raises_after_max_throttles() -> None:
    throttle = ClientError(
        {"Error": {"Code": "Throttling", "Message": "x"}, "ResponseMetadata": {}},
        "SendMessage",
    )
    sqs = AsyncMock()
    sqs.send_message = AsyncMock(side_effect=throttle)
    producer = SqsBulkEnqueue(
        queue_url="https://example/q",
        region_name="us-east-1",
        endpoint_url=None,
        max_attempts=2,
        sleeper=AsyncMock(),
        session=_fake_session(sqs),
    )
    bulk = BulkIntentV1(
        trace_id="t",
        batch_correlation_id="b3333333-3333-4333-8333-333333333333",
        idempotency_key="i",
        count=1,
        body="x",
        received_at_ms=0,
    )
    with pytest.raises(ClientError):
        await producer.enqueue(bulk)
    assert sqs.send_message.await_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_throttle_error_not_retried() -> None:
    err = ClientError(
        {
            "Error": {"Code": "InvalidParameterValue", "Message": "bad"},
            "ResponseMetadata": {},
        },
        "SendMessage",
    )
    sqs = AsyncMock()
    sqs.send_message = AsyncMock(side_effect=err)
    sleeper = AsyncMock()
    producer = SqsBulkEnqueue(
        queue_url="https://example/q",
        region_name="us-east-1",
        endpoint_url=None,
        max_attempts=5,
        sleeper=sleeper,
        session=_fake_session(sqs),
    )
    bulk = BulkIntentV1(
        trace_id="t",
        batch_correlation_id="b4444444-4444-4444-8444-444444444444",
        idempotency_key="i",
        count=1,
        body="x",
        received_at_ms=0,
    )
    with pytest.raises(ClientError):
        await producer.enqueue(bulk)
    assert sqs.send_message.await_count == 1
    sleeper.assert_not_awaited()
