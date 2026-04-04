"""P3: bulk queue → three SendUnitV1 on LocalStack (opt-in)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import random

import aioboto3
import boto3
import pytest

from inspectio.v3.expander.consumer import receive_and_expand_once
from inspectio.v3.expander.dedupe import ExpandedBulkDedupe
from inspectio.v3.expander.metrics import ExpansionMetrics
from inspectio.v3.schemas.bulk_intent import BulkIntentV1
from inspectio.v3.schemas.send_unit import SendUnitV1
from inspectio.v3.settings import (
    V3ExpanderSettings,
    sqs_client_kwargs_from_expander_settings,
)
from inspectio.v3.sqs.bulk_producer import SqsBulkEnqueue


def _expander_integration_enabled() -> bool:
    return os.environ.get("INSPECTIO_EXPANDER_INTEGRATION") == "1"


pytestmark = pytest.mark.skipif(
    not _expander_integration_enabled(),
    reason="Set INSPECTIO_EXPANDER_INTEGRATION=1 with LocalStack (see README P3)",
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_count_three_fanout_to_send_queues() -> None:
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    key = os.environ.get("AWS_ACCESS_KEY_ID", "test")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "test")
    sync = boto3.client(
        "sqs",
        region_name=region,
        endpoint_url=endpoint,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )
    bulk_url = sync.get_queue_url(QueueName="inspectio-v3-bulk")["QueueUrl"]
    k = int(os.environ.get("INSPECTIO_V3_SEND_SHARD_COUNT", "2"))
    send_urls = [
        sync.get_queue_url(QueueName=f"inspectio-v3-send-{i}")["QueueUrl"]
        for i in range(k)
    ]

    settings = V3ExpanderSettings(
        aws_endpoint_url=endpoint,
        aws_region=region,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        bulk_queue_url=bulk_url,
        send_shard_count=k,
        send_queue_urls=send_urls,
        receive_wait_seconds=5,
        bulk_visibility_timeout_seconds=60,
    )

    for url in [bulk_url, *send_urls]:
        with contextlib.suppress(Exception):
            sync.purge_queue(QueueUrl=url)

    bulk = BulkIntentV1(
        trace_id="int-expander",
        batch_correlation_id="99999999-9999-4999-8999-999999999999",
        idempotency_key="idem-exp",
        count=3,
        body="fanout-three",
        received_at_ms=42,
    )
    producer = SqsBulkEnqueue(
        queue_url=bulk_url,
        region_name=region,
        endpoint_url=endpoint,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )
    await producer.enqueue(bulk)

    session = aioboto3.Session()
    client_kw = sqs_client_kwargs_from_expander_settings(settings)
    dedupe = ExpandedBulkDedupe()
    metrics = ExpansionMetrics()
    async with session.client("sqs", **client_kw) as client:
        handled = await receive_and_expand_once(
            client,
            bulk_queue_url=bulk_url,
            wait_seconds=5,
            visibility_timeout_seconds=settings.bulk_visibility_timeout_seconds,
            dedupe=dedupe,
            send_queue_urls=send_urls,
            metrics=metrics,
            sleeper=asyncio.sleep,
            rng=random.Random(0),
        )
    assert handled is True
    assert metrics.expanded_units_published == 3

    received: list[SendUnitV1] = []
    for url in send_urls:
        resp = sync.receive_message(
            QueueUrl=url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=3,
        )
        for m in resp.get("Messages", []):
            received.append(SendUnitV1.model_validate_json(m["Body"]))

    assert len(received) == 3
    assert {u.batch_correlation_id for u in received} == {bulk.batch_correlation_id}
    assert all(u.body == "fanout-three" for u in received)
    assert all(u.received_at_ms == 42 for u in received)
