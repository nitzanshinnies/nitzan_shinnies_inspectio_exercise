"""Environment-backed settings for v3 (P2–P5: SQS, expander, worker, L1)."""

from __future__ import annotations

import json
from typing import Literal, Self

from pydantic import AliasChoices, Field, field_validator, model_validator
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
    expander_publish_concurrency: int = Field(
        default=48,
        ge=1,
        le=256,
        validation_alias="INSPECTIO_V3_EXPANDER_PUBLISH_CONCURRENCY",
    )
    expander_bulk_receive_max: int = Field(
        default=10,
        ge=1,
        le=10,
        validation_alias="INSPECTIO_V3_EXPANDER_BULK_RECEIVE_MAX",
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
    return _sqs_client_kwargs(
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
    )


class V3WorkerSettings(BaseSettings):
    """L4 send worker: one process per ``INSPECTIO_V3_WORKER_SEND_QUEUE_URL`` (shard)."""

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
    send_queue_url: str = Field(
        validation_alias="INSPECTIO_V3_WORKER_SEND_QUEUE_URL",
    )
    redis_url: str = Field(
        validation_alias=AliasChoices("REDIS_URL", "INSPECTIO_REDIS_URL"),
    )
    try_send_always_succeed: bool = Field(
        default=True,
        validation_alias="INSPECTIO_V3_TRY_SEND_ALWAYS_SUCCEED",
    )
    persist_queue_url: str | None = Field(
        default=None,
        validation_alias="INSPECTIO_V3_PERSIST_QUEUE_URL",
    )
    worker_wakeup_sec: float = Field(
        default=0.05,
        ge=0.01,
        le=2.0,
        validation_alias="INSPECTIO_V3_WORKER_WAKEUP_SEC",
    )
    worker_receive_pollers: int = Field(
        default=2,
        ge=1,
        le=8,
        validation_alias="INSPECTIO_V3_WORKER_RECEIVE_POLLERS",
    )
    worker_record_outcomes: bool = Field(
        default=True,
        validation_alias="INSPECTIO_V3_WORKER_RECORD_OUTCOMES",
    )
    worker_recovery_enabled: bool = Field(
        default=False,
        validation_alias="INSPECTIO_V3_WORKER_RECOVERY_ENABLED",
    )
    worker_recovery_shard: int = Field(
        default=0,
        ge=0,
        validation_alias="INSPECTIO_V3_WORKER_RECOVERY_SHARD",
    )
    worker_recovery_s3_bucket: str | None = Field(
        default=None,
        validation_alias="INSPECTIO_V3_PERSISTENCE_S3_BUCKET",
    )
    worker_recovery_s3_prefix: str = Field(
        default="state",
        validation_alias="INSPECTIO_V3_PERSISTENCE_S3_PREFIX",
    )

    @field_validator("persist_queue_url", mode="before")
    @classmethod
    def _persist_url_empty_as_none(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return str(value).strip()

    @field_validator("worker_recovery_s3_bucket", mode="before")
    @classmethod
    def _empty_bucket_as_none(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return str(value).strip()


def sqs_client_kwargs_from_worker_settings(
    settings: V3WorkerSettings,
) -> dict[str, str]:
    return _sqs_client_kwargs(
        region_name=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
    )


def _sqs_client_kwargs(
    *,
    region_name: str,
    endpoint_url: str | None,
    access_key_id: str | None,
    secret_access_key: str | None,
) -> dict[str, str]:
    kw: dict[str, str] = {"region_name": region_name}
    if endpoint_url:
        kw["endpoint_url"] = endpoint_url
    if access_key_id:
        kw["aws_access_key_id"] = access_key_id
    if secret_access_key:
        kw["aws_secret_access_key"] = secret_access_key
    return kw


class V3L1Settings(BaseSettings):
    """L1 edge: proxy browser API traffic to L2 (P5)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    l2_base_url: str = Field(validation_alias="INSPECTIO_L2_BASE_URL")
    l2_http_timeout_sec: float = Field(
        default=120.0,
        ge=5.0,
        validation_alias="INSPECTIO_L1_L2_TIMEOUT_SEC",
    )
    l2_max_connections: int = Field(
        default=2048,
        ge=32,
        le=4096,
        validation_alias="INSPECTIO_L1_L2_MAX_CONNECTIONS",
    )


class V3PersistenceSettings(BaseSettings):
    """Feature flags/config for persistence transport integration (P12.1/P12.2)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    persistence_emit_enabled: bool = Field(
        default=False,
        validation_alias="INSPECTIO_V3_PERSIST_EMIT_ENABLED",
    )
    persistence_durability_mode: Literal["best_effort", "strict"] = Field(
        default="best_effort",
        validation_alias="INSPECTIO_V3_PERSIST_DURABILITY_MODE",
    )
    persist_transport_queue_url: str | None = Field(
        default=None,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URL",
    )
    persist_transport_dlq_url: str | None = Field(
        default=None,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_DLQ_URL",
    )
    persist_transport_shard_count: int = Field(
        default=1,
        ge=1,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_SHARD_COUNT",
    )
    persist_transport_queue_urls: list[str] = Field(
        default_factory=list,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URLS",
    )
    persist_transport_dlq_urls: list[str] = Field(
        default_factory=list,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_DLQ_URLS",
    )
    persist_transport_max_attempts: int = Field(
        default=4,
        ge=1,
        le=10,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_MAX_ATTEMPTS",
    )
    persist_transport_backoff_base_ms: int = Field(
        default=50,
        ge=1,
        le=5_000,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_BACKOFF_BASE_MS",
    )
    persist_transport_backoff_max_ms: int = Field(
        default=2_000,
        ge=1,
        le=30_000,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_BACKOFF_MAX_MS",
    )
    persist_transport_backoff_jitter_fraction: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_BACKOFF_JITTER",
    )
    persist_transport_max_inflight_events: int = Field(
        default=4_096,
        ge=1,
        le=100_000,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_MAX_INFLIGHT",
    )
    persist_transport_batch_max_events: int = Field(
        default=10,
        ge=1,
        le=10,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_BATCH_MAX_EVENTS",
    )

    @field_validator(
        "persist_transport_queue_url", "persist_transport_dlq_url", mode="before"
    )
    @classmethod
    def _empty_url_as_none(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return str(value).strip()

    @field_validator(
        "persist_transport_queue_urls", "persist_transport_dlq_urls", mode="before"
    )
    @classmethod
    def _url_list_from_csv_or_json(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            if not value.strip():
                return []
            if value.lstrip().startswith("["):
                decoded = json.loads(value)
                if not isinstance(decoded, list):
                    raise TypeError(value)
                return [str(item).strip() for item in decoded if str(item).strip()]
            return [item.strip() for item in value.split(",") if item.strip()]
        raise TypeError(value)

    @model_validator(mode="after")
    def _validate_sharded_transport(self) -> Self:
        if self.persist_transport_queue_urls:
            if (
                len(self.persist_transport_queue_urls)
                != self.persist_transport_shard_count
            ):
                msg = (
                    "INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URLS length must equal "
                    f"INSPECTIO_V3_PERSIST_TRANSPORT_SHARD_COUNT ({self.persist_transport_shard_count}), "
                    f"got {len(self.persist_transport_queue_urls)}"
                )
                raise ValueError(msg)
            if (
                self.persist_transport_dlq_urls
                and len(self.persist_transport_dlq_urls)
                != self.persist_transport_shard_count
            ):
                msg = (
                    "INSPECTIO_V3_PERSIST_TRANSPORT_DLQ_URLS length must equal "
                    f"INSPECTIO_V3_PERSIST_TRANSPORT_SHARD_COUNT ({self.persist_transport_shard_count}), "
                    f"got {len(self.persist_transport_dlq_urls)}"
                )
                raise ValueError(msg)
        elif self.persist_transport_queue_url is None and self.persistence_emit_enabled:
            raise ValueError(
                "INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URL or "
                "INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URLS is required when "
                "INSPECTIO_V3_PERSIST_EMIT_ENABLED=true"
            )
        return self


class V3PersistenceWriterSettings(BaseSettings):
    """Persistence writer process settings (P12.3)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    aws_endpoint_url: str | None = Field(
        default=None,
        validation_alias="AWS_ENDPOINT_URL",
    )
    aws_region: str = Field(default="us-east-1", validation_alias="AWS_DEFAULT_REGION")
    aws_access_key_id: str | None = Field(
        default=None,
        validation_alias="AWS_ACCESS_KEY_ID",
    )
    aws_secret_access_key: str | None = Field(
        default=None,
        validation_alias="AWS_SECRET_ACCESS_KEY",
    )
    persist_transport_queue_url: str | None = Field(
        default=None,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URL",
    )
    persist_transport_shard_count: int = Field(
        default=1,
        ge=1,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_SHARD_COUNT",
    )
    persist_transport_queue_urls: list[str] = Field(
        default_factory=list,
        validation_alias="INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URLS",
    )
    writer_shard_id: int = Field(
        default=0,
        ge=0,
        validation_alias="INSPECTIO_V3_WRITER_SHARD_ID",
    )
    persistence_s3_bucket: str = Field(
        validation_alias="INSPECTIO_V3_PERSISTENCE_S3_BUCKET",
    )
    persistence_s3_prefix: str = Field(
        default="state",
        validation_alias="INSPECTIO_V3_PERSISTENCE_S3_PREFIX",
    )
    writer_receive_wait_seconds: int = Field(
        default=20,
        ge=0,
        le=20,
        validation_alias="INSPECTIO_V3_WRITER_RECEIVE_WAIT_SECONDS",
    )
    writer_receive_max_events: int = Field(
        default=10,
        ge=1,
        le=10,
        validation_alias="INSPECTIO_V3_WRITER_RECEIVE_MAX_EVENTS",
    )
    persistence_ack_delete_max_concurrency: int = Field(
        default=6,
        ge=1,
        le=8,
        validation_alias="INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY",
    )
    writer_flush_max_events: int = Field(
        default=500,
        ge=1,
        le=50_000,
        validation_alias="INSPECTIO_V3_WRITER_FLUSH_MAX_EVENTS",
    )
    writer_flush_min_batch_events: int = Field(
        default=1,
        ge=1,
        validation_alias=AliasChoices(
            "INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS",
            "INSPECTIO_V3_WRITER_FLUSH_MIN_BATCH_EVENTS",
        ),
    )
    writer_flush_interval_ms: int = Field(
        default=1_000,
        ge=1,
        le=60_000,
        validation_alias=AliasChoices(
            "INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_INTERVAL_MS",
            "INSPECTIO_V3_WRITER_FLUSH_INTERVAL_MS",
        ),
    )
    persistence_checkpoint_every_n_flushes: int = Field(
        default=1,
        ge=1,
        le=20,
        validation_alias="INSPECTIO_V3_PERSISTENCE_CHECKPOINT_EVERY_N_FLUSHES",
    )
    writer_dedupe_event_id_cap: int = Field(
        default=200_000,
        ge=64,
        le=1_000_000,
        validation_alias="INSPECTIO_V3_WRITER_DEDUPE_EVENT_ID_CAP",
    )
    writer_write_max_attempts: int = Field(
        default=4,
        ge=1,
        le=10,
        validation_alias="INSPECTIO_V3_WRITER_WRITE_MAX_ATTEMPTS",
    )
    writer_write_backoff_base_ms: int = Field(
        default=50,
        ge=1,
        le=5_000,
        validation_alias="INSPECTIO_V3_WRITER_WRITE_BACKOFF_BASE_MS",
    )
    writer_write_backoff_max_ms: int = Field(
        default=2_000,
        ge=1,
        le=30_000,
        validation_alias="INSPECTIO_V3_WRITER_WRITE_BACKOFF_MAX_MS",
    )
    writer_write_backoff_jitter: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        validation_alias="INSPECTIO_V3_WRITER_WRITE_BACKOFF_JITTER",
    )
    writer_idle_sleep_sec: float = Field(
        default=0.2,
        ge=0.01,
        le=5.0,
        validation_alias="INSPECTIO_V3_WRITER_IDLE_SLEEP_SEC",
    )
    writer_pipeline_enable: bool = Field(
        default=True,
        validation_alias="INSPECTIO_V3_WRITER_PIPELINE_ENABLE",
    )
    writer_ack_queue_max_events: int = Field(
        default=20_000,
        ge=100,
        le=500_000,
        validation_alias="INSPECTIO_V3_WRITER_ACK_QUEUE_MAX_EVENTS",
    )
    writer_flush_loop_sleep_ms: int = Field(
        default=10,
        ge=1,
        le=1_000,
        validation_alias="INSPECTIO_V3_WRITER_FLUSH_LOOP_SLEEP_MS",
    )
    writer_receive_loop_parallelism: int = Field(
        default=1,
        ge=1,
        le=4,
        validation_alias="INSPECTIO_V3_WRITER_RECEIVE_LOOP_PARALLELISM",
    )
    writer_observability_snapshot_interval_sec: int = Field(
        default=30,
        ge=1,
        le=300,
        validation_alias="INSPECTIO_V3_WRITER_OBS_SNAPSHOT_INTERVAL_SEC",
    )
    writer_observability_queue_age_sample_interval_sec: int = Field(
        default=30,
        ge=1,
        le=300,
        validation_alias="INSPECTIO_V3_WRITER_QUEUE_AGE_SAMPLE_INTERVAL_SEC",
    )
    writer_observability_queue_age_timeout_sec: float = Field(
        default=1.0,
        gt=0.0,
        le=5.0,
        validation_alias="INSPECTIO_V3_WRITER_QUEUE_AGE_TIMEOUT_SEC",
    )

    @field_validator("persist_transport_queue_url", mode="before")
    @classmethod
    def _writer_empty_url_as_none(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return str(value).strip()

    @field_validator("persist_transport_queue_urls", mode="before")
    @classmethod
    def _writer_url_list_from_csv_or_json(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            if not value.strip():
                return []
            if value.lstrip().startswith("["):
                decoded = json.loads(value)
                if not isinstance(decoded, list):
                    raise TypeError(value)
                return [str(item).strip() for item in decoded if str(item).strip()]
            return [item.strip() for item in value.split(",") if item.strip()]
        raise TypeError(value)

    @model_validator(mode="after")
    def _validate_writer_shard_binding(self) -> Self:
        if self.persist_transport_queue_urls:
            if (
                len(self.persist_transport_queue_urls)
                != self.persist_transport_shard_count
            ):
                msg = (
                    "INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URLS length must equal "
                    f"INSPECTIO_V3_PERSIST_TRANSPORT_SHARD_COUNT ({self.persist_transport_shard_count}), "
                    f"got {len(self.persist_transport_queue_urls)}"
                )
                raise ValueError(msg)
            if self.writer_shard_id >= self.persist_transport_shard_count:
                msg = (
                    "INSPECTIO_V3_WRITER_SHARD_ID must be in range [0, "
                    f"{self.persist_transport_shard_count - 1}], got {self.writer_shard_id}"
                )
                raise ValueError(msg)
        elif self.persist_transport_queue_url is None:
            raise ValueError(
                "INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URL or "
                "INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URLS is required for writer"
            )
        if self.writer_flush_min_batch_events > self.writer_flush_max_events:
            msg = (
                "INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS must be <= "
                "INSPECTIO_V3_WRITER_FLUSH_MAX_EVENTS"
            )
            raise ValueError(msg)
        return self

    def resolved_transport_queue_url(self) -> str:
        if self.persist_transport_queue_urls:
            return self.persist_transport_queue_urls[self.writer_shard_id]
        if self.persist_transport_queue_url is None:
            raise ValueError("missing persistence transport queue URL")
        return self.persist_transport_queue_url
