"""Shared botocore client tuning for high-throughput v3 services."""

from __future__ import annotations

from typing import Any

from botocore.config import Config

_V3_CONFIG = Config(
    max_pool_connections=500,
    retries={"max_attempts": 5, "mode": "adaptive"},
    tcp_keepalive=True,
)


def v3_botocore_config() -> Config:
    """Connection pool + adaptive retries for aioboto3 ``Session().client(...)``."""
    return _V3_CONFIG


def augment_client_kwargs_with_v3_config(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``kwargs`` with ``config=v3_botocore_config()`` applied."""
    out = dict(kwargs)
    out["config"] = v3_botocore_config()
    return out
