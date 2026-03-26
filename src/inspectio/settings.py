"""Pydantic settings for inspectio services (§29.4)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings shared across processes."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    inspectio_env: str = Field(default="dev", alias="INSPECTIO_ENV")
    inspectio_aws_region: str = Field(default="us-east-1", alias="INSPECTIO_AWS_REGION")
    inspectio_s3_bucket: str = Field(default="", alias="INSPECTIO_S3_BUCKET")
    inspectio_ingest_queue_url: str = Field(
        default="",
        alias="INSPECTIO_INGEST_QUEUE_URL",
    )
    inspectio_total_shards: int = Field(default=1024, alias="INSPECTIO_TOTAL_SHARDS")
    inspectio_worker_replicas: int = Field(default=1, alias="INSPECTIO_WORKER_REPLICAS")
    inspectio_worker_index: int = Field(default=0, alias="INSPECTIO_WORKER_INDEX")
    inspectio_redis_url: str = Field(
        default="redis://127.0.0.1:6379/0",
        alias="INSPECTIO_REDIS_URL",
    )
    inspectio_notification_base_url: str = Field(
        default="http://127.0.0.1:8081",
        alias="INSPECTIO_NOTIFICATION_BASE_URL",
    )
    inspectio_sms_url: str = Field(
        default="http://127.0.0.1:8090", alias="INSPECTIO_SMS_URL"
    )
    inspectio_default_to_e164: str = Field(
        default="+10000000000",
        alias="INSPECTIO_DEFAULT_TO_E164",
    )
    inspectio_wakeup_interval_ms: int = Field(
        default=500,
        alias="INSPECTIO_WAKEUP_INTERVAL_MS",
    )
    inspectio_max_parallel_sends_per_shard: int = Field(
        default=64,
        alias="INSPECTIO_MAX_PARALLEL_SENDS_PER_SHARD",
    )
    inspectio_sms_http_timeout_sec: int = Field(
        default=5,
        alias="INSPECTIO_SMS_HTTP_TIMEOUT_SEC",
    )
    inspectio_repeat_max_count: int = Field(
        default=100_000,
        alias="INSPECTIO_REPEAT_MAX_COUNT",
    )
    inspectio_ingest_buffer_max_messages: int = Field(
        default=10_000,
        alias="INSPECTIO_INGEST_BUFFER_MAX_MESSAGES",
    )
    inspectio_idempotency_ttl_sec: int = Field(
        default=86_400,
        alias="INSPECTIO_IDEMPOTENCY_TTL_SEC",
    )
    inspectio_outcomes_max_limit: int = Field(
        default=1_000,
        alias="INSPECTIO_OUTCOMES_MAX_LIMIT",
    )
    inspectio_journal_flush_interval_ms: int = Field(
        default=50,
        alias="INSPECTIO_JOURNAL_FLUSH_INTERVAL_MS",
    )
    inspectio_journal_flush_max_lines: int = Field(
        default=64,
        alias="INSPECTIO_JOURNAL_FLUSH_MAX_LINES",
    )
    inspectio_snapshot_interval_sec: int = Field(
        default=60,
        alias="INSPECTIO_SNAPSHOT_INTERVAL_SEC",
    )
    inspectio_api_port: int = Field(default=8000, alias="INSPECTIO_API_PORT")
    inspectio_notification_port: int = Field(
        default=8081,
        alias="INSPECTIO_NOTIFICATION_PORT",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-level cached settings instance."""
    return Settings()
