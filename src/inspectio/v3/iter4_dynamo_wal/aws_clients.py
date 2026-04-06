"""Shared aioboto3 client configuration (connection pool sizing)."""

from __future__ import annotations

from typing import Any

import aioboto3
from botocore.config import Config

from inspectio.v3.iter4_dynamo_wal.constants import MAX_POOL_CONNECTIONS


def botocore_high_throughput_config() -> Config:
    return Config(
        max_pool_connections=MAX_POOL_CONNECTIONS,
        retries={"max_attempts": 10, "mode": "adaptive"},
        tcp_keepalive=True,
    )


def session_kwargs(*, region_name: str, endpoint_url: str | None) -> dict[str, Any]:
    kw: dict[str, Any] = {"region_name": region_name}
    if endpoint_url:
        kw["endpoint_url"] = endpoint_url
    return kw


def aioboto3_session() -> aioboto3.Session:
    return aioboto3.Session()
