"""Environment-backed settings for v3 (P2 SQS, P3 expander)."""

from __future__ import annotations

from typing import Self

from pydantic import Field, field_validator, model_validator
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


class V3ExpanderSettings(BaseSettings):
    """Bulk consumer + sharded send publishers (P3)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
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
    send_shard_count: int = Field(
        default=1, ge=1, validation_alias="INSPECTIO_V3_SEND_SHARD_COUNT"
    )
    send_queue_urls: list[str] = Field(validation_alias="INSPECTIO_V3_SEND_QUEUE_URLS")
    receive_wait_seconds: int = Field(
        default=20, ge=0, le=20, validation_alias="INSPECTIO_V3_EXPANDER_WAIT_SECONDS"
    )
    bulk_visibility_timeout_seconds: int = Field(
        default=120, ge=1, validation_alias="INSPECTIO_V3_BULK_VISIBILITY_TIMEOUT"
    )

    @field_validator("send_queue_urls", mode="before")
    @classmethod
    def _send_urls_from_csv(cls, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        if isinstance(value, str):
            return [x.strip() for x in value.split(",") if x.strip()]
        raise TypeError(value)

    @model_validator(mode="after")
    def _urls_match_shard_count(self) -> Self:
        if len(self.send_queue_urls) != self.send_shard_count:
            msg = (
                f"INSPECTIO_V3_SEND_QUEUE_URLS must contain {self.send_shard_count} "
                f"comma-separated URLs, got {len(self.send_queue_urls)}"
            )
            raise ValueError(msg)
        return self


def sqs_client_kwargs_from_expander_settings(
    settings: V3ExpanderSettings,
) -> dict[str, str]:
    """Keyword args for ``aioboto3.Session().client('sqs', ...)``."""
    kw: dict[str, str] = {"region_name": settings.aws_region}
    if settings.aws_endpoint_url:
        kw["endpoint_url"] = settings.aws_endpoint_url
    if settings.aws_access_key_id:
        kw["aws_access_key_id"] = settings.aws_access_key_id
    if settings.aws_secret_access_key:
        kw["aws_secret_access_key"] = settings.aws_secret_access_key
    return kw
