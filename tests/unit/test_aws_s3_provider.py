"""``AwsS3Provider`` contract against moto (AWS emulation)."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from inspectio_exercise.persistence.aws_s3 import AwsS3Provider

_BUCKET = "inspectio-test-bucket"
_REGION = "us-east-1"


@pytest.fixture(autouse=True)
def _aws_test_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", _REGION)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_put_get_delete_round_trip() -> None:
    with mock_aws():
        boto3.client("s3", region_name=_REGION).create_bucket(Bucket=_BUCKET)
        s3 = AwsS3Provider(_BUCKET, region_name=_REGION)
        await s3.put_object("state/pending/shard-0/x.json", b'{"x":1}')
        assert await s3.get_object("state/pending/shard-0/x.json") == b'{"x":1}'
        await s3.delete_object("state/pending/shard-0/x.json")
        with pytest.raises(KeyError):
            await s3.get_object("state/pending/shard-0/x.json")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_missing_keyerror() -> None:
    with mock_aws():
        boto3.client("s3", region_name=_REGION).create_bucket(Bucket=_BUCKET)
        s3 = AwsS3Provider(_BUCKET, region_name=_REGION)
        with pytest.raises(KeyError) as exc:
            await s3.get_object("missing.json")
        assert exc.value.args[0] == "missing.json"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_missing_idempotent() -> None:
    with mock_aws():
        boto3.client("s3", region_name=_REGION).create_bucket(Bucket=_BUCKET)
        s3 = AwsS3Provider(_BUCKET, region_name=_REGION)
        await s3.delete_object("never-existed.json")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_prefix_sorted_and_max_keys() -> None:
    with mock_aws():
        boto3.client("s3", region_name=_REGION).create_bucket(Bucket=_BUCKET)
        s3 = AwsS3Provider(_BUCKET, region_name=_REGION)
        await s3.put_object("p/c", b"")
        await s3.put_object("p/a", b"")
        await s3.put_object("p/b", b"")
        out = await s3.list_prefix("p/")
        assert [row["Key"] for row in out] == ["p/a", "p/b", "p/c"]
        limited = await s3.list_prefix("p/", max_keys=2)
        assert [row["Key"] for row in limited] == ["p/a", "p/b"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rejects_bad_keys_like_local_policy() -> None:
    with mock_aws():
        boto3.client("s3", region_name=_REGION).create_bucket(Bucket=_BUCKET)
        s3 = AwsS3Provider(_BUCKET, region_name=_REGION)
        with pytest.raises(ValueError):
            await s3.put_object("", b"x")
        with pytest.raises(ValueError):
            await s3.put_object("/abs", b"x")
