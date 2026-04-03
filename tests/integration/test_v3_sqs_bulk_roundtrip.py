"""P2: LocalStack SQS send → receive → BulkIntentV1 (opt-in integration)."""

from __future__ import annotations

import os

import boto3
import pytest

from inspectio.v3.schemas.bulk_intent import BulkIntentV1
from inspectio.v3.sqs.bulk_producer import SqsBulkEnqueue


def _sqs_integration_enabled() -> bool:
    return os.environ.get("INSPECTIO_SQS_INTEGRATION") == "1" and bool(
        os.environ.get("INSPECTIO_V3_BULK_QUEUE_URL")
    )


pytestmark = pytest.mark.skipif(
    not _sqs_integration_enabled(),
    reason="Set INSPECTIO_SQS_INTEGRATION=1 and INSPECTIO_V3_BULK_QUEUE_URL (LocalStack up)",
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_send_message_receive_bulk_intent_roundtrip() -> None:
    queue_url = os.environ["INSPECTIO_V3_BULK_QUEUE_URL"]
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    key = os.environ.get("AWS_ACCESS_KEY_ID", "test")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "test")

    producer = SqsBulkEnqueue(
        queue_url=queue_url,
        region_name=region,
        endpoint_url=endpoint,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )
    bulk = BulkIntentV1(
        trace_id="int-trace",
        batch_correlation_id="b5555555-5555-4555-8555-555555555555",
        idempotency_key="int-idem",
        count=7,
        body="integration-body",
        received_at_ms=99,
    )
    await producer.enqueue(bulk)

    sync = boto3.client(
        "sqs",
        region_name=region,
        endpoint_url=endpoint,
        aws_access_key_id=key,
        aws_secret_access_key=secret,
    )
    resp = sync.receive_message(
        QueueUrl=queue_url, WaitTimeSeconds=5, MaxNumberOfMessages=1
    )
    messages = resp.get("Messages", [])
    assert messages, "no message received from bulk queue"
    parsed = BulkIntentV1.model_validate_json(messages[0]["Body"])
    assert parsed == bulk
