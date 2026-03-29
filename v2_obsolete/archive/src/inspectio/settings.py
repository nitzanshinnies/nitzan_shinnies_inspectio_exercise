"""Pydantic settings (blueprint)."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings; names align with blueprint"""

    model_config = SettingsConfigDict(
        env_prefix="INSPECTIO_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    env: str = Field(default="dev")
    aws_region: str = Field(default="us-east-1")
    aws_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INSPECTIO_AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL"),
    )
    s3_bucket: str = Field(default="")
    ingest_queue_url: str = Field(default="")
    max_sqs_fifo_inflight_groups: int = Field(default=64, ge=1)
    sqs_receive_concurrency: int = Field(default=4, ge=1, le=32)

    total_shards: int = Field(default=1024, ge=1)
    worker_replicas: int = Field(default=1, ge=1)
    worker_index: int = Field(default=0, ge=0)

    redis_url: str = Field(default="redis://127.0.0.1:6379/0")

    notification_base_url: str = Field(default="http://127.0.0.1:8081")
    sms_url: str = Field(default="http://127.0.0.1:8090")
    sms_http_timeout_sec: float = Field(default=5.0, gt=0)

    default_to_e164: str = Field(default="+10000000000")
    wakeup_interval_ms: int = Field(default=500, ge=1)
    max_parallel_sends_per_shard: int = Field(default=64, ge=1)
    repeat_max_count: int = Field(default=100_000, ge=1)
    ingest_buffer_max_messages: int = Field(default=200_000, ge=1)
    idempotency_ttl_sec: int = Field(default=86_400, ge=1)
    outcomes_max_limit: int = Field(default=1000, ge=1)

    journal_flush_interval_ms: int = Field(default=50, ge=1)
    journal_flush_max_lines: int = Field(default=64, ge=1)
    snapshot_interval_sec: int = Field(default=60, ge=1)

    api_port: int = Field(default=8000, ge=1)
    notification_port: int = Field(default=8081, ge=1)
