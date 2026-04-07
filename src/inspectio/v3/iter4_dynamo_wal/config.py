"""Environment-driven settings for Iteration 4 (DynamoDB + S3 WAL) path."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from inspectio.v3.iter4_dynamo_wal.constants import (
    DEFAULT_RECONCILE_INTERVAL_MS,
    DEFAULT_TOTAL_SHARDS,
    DEFAULT_TOTAL_WORKERS,
    GSI_SCHEDULING_INDEX_DEFAULT_NAME,
    WAL_FLUSH_INTERVAL_SEC,
)


class Iter4DynamoWalSettings(BaseSettings):
    """All keys use env prefix ``INSPECTIO_V3_ITER4_`` (e.g. ``INSPECTIO_V3_ITER4_S3_BUCKET``)."""

    model_config = SettingsConfigDict(
        env_prefix="INSPECTIO_V3_ITER4_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    aws_region: str = "us-east-1"
    aws_endpoint_url: str | None = Field(
        default=None,
        description="Optional LocalStack / custom endpoint (same idea as AWS_ENDPOINT_URL).",
    )

    dynamodb_table_name: str = "sms_messages"
    gsi_scheduling_index_name: str = GSI_SCHEDULING_INDEX_DEFAULT_NAME

    s3_bucket: str = ""
    s3_wal_prefix: str = "wal"

    total_shards: int = Field(default=DEFAULT_TOTAL_SHARDS, ge=1)
    total_workers: int = Field(default=DEFAULT_TOTAL_WORKERS, ge=1)

    wal_writer_id: str = Field(
        default="api",
        description="Logical WAL partition for API process (S3 path segment).",
    )

    reconcile_interval_ms: int = Field(
        default=DEFAULT_RECONCILE_INTERVAL_MS,
        ge=50,
        description="How often workers pull due rows from DynamoDB into the heap.",
    )

    wal_flush_interval_sec: float = Field(
        default=WAL_FLUSH_INTERVAL_SEC,
        gt=0,
        description="S3 WAL background task: flush buffered events at this cadence (seconds).",
    )


def iter4_settings_from_env() -> Iter4DynamoWalSettings:
    return Iter4DynamoWalSettings()
