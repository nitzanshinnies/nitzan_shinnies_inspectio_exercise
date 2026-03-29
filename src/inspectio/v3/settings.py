"""Environment-backed settings for v3 (P2 SQS)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from inspectio.v3.sqs.bulk_producer import SqsBulkEnqueue


class V3SqsSettings(BaseSettings):
    """AWS / SQS endpoints for v3 bulk enqueue (standard queue)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    aws_endpoint_url: str | None = Field(
        default=None, validation_alias="AWS_ENDPOINT_URL"
    )
    aws_region: str = Field(default="us-east-1", validation_alias="AWS_DEFAULT_REGION")
    aws_access_key_id: str | None = Field(
        default=None, validation_alias="AWS_ACCESS_KEY_ID"
    )
    aws_secret_access_key: str | None = Field(
        default=None, validation_alias="AWS_SECRET_ACCESS_KEY"
    )
    bulk_queue_url: str = Field(validation_alias="INSPECTIO_V3_BULK_QUEUE_URL")


def build_sqs_bulk_enqueue_from_env() -> SqsBulkEnqueue:
    """Construct ``SqsBulkEnqueue`` from environment (see README P2)."""
    settings = V3SqsSettings()
    return SqsBulkEnqueue(
        queue_url=settings.bulk_queue_url,
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
