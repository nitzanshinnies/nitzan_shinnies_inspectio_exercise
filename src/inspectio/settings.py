"""Pydantic settings (§29.4 subset for ingest / SQS-P1)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings; names align with blueprint §29.4."""

    model_config = SettingsConfigDict(
        env_prefix="INSPECTIO_",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    aws_region: str = Field(default="us-east-1")
    ingest_queue_url: str = Field(default="")
    max_sqs_fifo_inflight_groups: int = Field(default=64, ge=1)
