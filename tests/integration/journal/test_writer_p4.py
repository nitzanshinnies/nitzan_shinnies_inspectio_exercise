"""P4 journal writer integration tests (flush policy + throttling retry)."""

from __future__ import annotations

import asyncio
import gzip
from dataclasses import dataclass
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from inspectio.journal.records import JournalRecordV1
from inspectio.journal.writer import JournalWriter


@dataclass
class _PutCall:
    bucket: str
    key: str
    body: bytes
    content_encoding: str
    content_type: str


class _FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[_PutCall] = []
        self.failures_before_success = 0

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise RuntimeError("503 SlowDown")
        self.calls.append(
            _PutCall(
                bucket=str(kwargs["Bucket"]),
                key=str(kwargs["Key"]),
                body=bytes(kwargs["Body"]),
                content_encoding=str(kwargs["ContentEncoding"]),
                content_type=str(kwargs["ContentType"]),
            )
        )
        return {"ETag": "x"}


class _MotoAsyncS3Client:
    def __init__(self, *, bucket: str) -> None:
        self._client = boto3.client("s3", region_name="us-east-1")
        self._bucket = bucket

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self._client.put_object(**kwargs)
        )

    def get_object_bytes(self, key: str) -> bytes:
        obj = self._client.get_object(Bucket=self._bucket, Key=key)
        return bytes(obj["Body"].read())


class _FailThenMotoS3Client:
    def __init__(self, *, moto_client: _MotoAsyncS3Client, failures: int) -> None:
        self._moto_client = moto_client
        self._remaining_failures = failures

    async def put_object(self, **kwargs: Any) -> dict[str, Any]:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise ClientError(
                {
                    "Error": {
                        "Code": "SlowDown",
                        "Message": "Reduce your request rate",
                    },
                    "ResponseMetadata": {"HTTPStatusCode": 503},
                },
                "PutObject",
            )
        return await self._moto_client.put_object(**kwargs)


def _record(record_index: int, ts_ms: int = 1_700_000_000_000) -> JournalRecordV1:
    return JournalRecordV1.model_validate(
        {
            "v": 1,
            "type": "DISPATCH_SCHEDULED",
            "shardId": 7,
            "messageId": f"m-{record_index}",
            "tsMs": ts_ms,
            "recordIndex": record_index,
            "payload": {"reason": "immediate"},
        }
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_p4_flushes_when_pending_lines_reaches_max_moto() -> None:
    with mock_aws():
        bucket = "inspectio-test-bucket"
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket)
        s3 = _MotoAsyncS3Client(bucket=bucket)
        writer = JournalWriter(
            s3_client=s3,
            bucket=bucket,
            flush_interval_ms=50,
            flush_max_lines=2,
        )
        await writer.append(_record(1))
        await writer.append(_record(2))

        key = "state/journal/7/2023/11/14/22/1700000000000-000001.ndjson.gz"
        text = gzip.decompress(s3.get_object_bytes(key)).decode("utf-8")
        assert text.count("\n") == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_p4_flushes_when_elapsed_interval_reached() -> None:
    s3 = _FakeS3Client()
    writer = JournalWriter(
        s3_client=s3,
        bucket="bucket-a",
        flush_interval_ms=50,
        flush_max_lines=64,
    )
    await writer.append(_record(1, ts_ms=1000))
    await writer.flush_if_due(now_ms=1049)
    assert len(s3.calls) == 0

    await writer.flush_if_due(now_ms=1050)
    assert len(s3.calls) == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_p4_uses_date_partitioned_key_with_segment_start_and_sequence() -> None:
    s3 = _FakeS3Client()
    writer = JournalWriter(
        s3_client=s3,
        bucket="bucket-a",
        flush_interval_ms=1,
        flush_max_lines=1,
    )
    await writer.append(_record(1, ts_ms=1_700_000_000_000))
    await writer.append(_record(2, ts_ms=1_700_000_000_123))

    assert len(s3.calls) == 2
    first_key = s3.calls[0].key
    second_key = s3.calls[1].key
    assert "state/journal/7/2023/11/14/22/" in first_key
    assert first_key.endswith("-000001.ndjson.gz")
    assert second_key.endswith("-000002.ndjson.gz")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tc_flt_002_retries_throttled_put_object_with_backoff_and_metric() -> (
    None
):
    with mock_aws():
        bucket = "inspectio-test-bucket"
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=bucket)
        moto_client = _MotoAsyncS3Client(bucket=bucket)
        s3 = _FailThenMotoS3Client(moto_client=moto_client, failures=2)
        sleeps: list[float] = []

        async def _sleep(seconds: float) -> None:
            sleeps.append(seconds)

        writer = JournalWriter(
            s3_client=s3,
            bucket=bucket,
            flush_interval_ms=1,
            flush_max_lines=1,
            max_retry_attempts=4,
            retry_backoff_sec=0.01,
            sleep_func=_sleep,
        )
        await writer.append(_record(1))

        key = "state/journal/7/2023/11/14/22/1700000000000-000001.ndjson.gz"
        body = moto_client.get_object_bytes(key)
        assert gzip.decompress(body).decode("utf-8").count("\n") == 1
        assert sleeps == [0.01, 0.02]
        assert writer.s3_errors_total == 2
