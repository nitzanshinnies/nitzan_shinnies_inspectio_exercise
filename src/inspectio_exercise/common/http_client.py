"""Shared defaults for outbound ``httpx`` clients to peer services."""

from __future__ import annotations

import os
from typing import Final

import httpx

_DEFAULT_HTTP_CLIENT_TIMEOUT_SEC: Final[float] = 60.0
_DEFAULT_HTTPX_MAX_CONNECTIONS: Final[int] = 256
_DEFAULT_HTTPX_MAX_KEEPALIVE_CONNECTIONS: Final[int] = 64
_DEFAULT_HTTPX_POOL_TIMEOUT_SEC: Final[float] = 30.0

HTTP_CLIENT_TIMEOUT_SEC: float = float(
    os.environ.get(
        "INSPECTIO_HTTP_CLIENT_TIMEOUT_SEC",
        str(_DEFAULT_HTTP_CLIENT_TIMEOUT_SEC),
    ),
)


def peer_httpx_limits() -> httpx.Limits:
    """Connection pool sizing for service-to-service clients (avoids ``PoolTimeout`` under burst)."""
    return httpx.Limits(
        max_connections=int(
            os.environ.get(
                "INSPECTIO_HTTPX_MAX_CONNECTIONS",
                str(_DEFAULT_HTTPX_MAX_CONNECTIONS),
            )
        ),
        max_keepalive_connections=int(
            os.environ.get(
                "INSPECTIO_HTTPX_MAX_KEEPALIVE_CONNECTIONS",
                str(_DEFAULT_HTTPX_MAX_KEEPALIVE_CONNECTIONS),
            )
        ),
    )


def peer_httpx_timeout(*, total_sec: float) -> httpx.Timeout:
    """Read/write bound to ``total_sec``; pool wait separate (queueing for a free connection)."""
    pool = float(
        os.environ.get(
            "INSPECTIO_HTTPX_POOL_TIMEOUT_SEC",
            str(_DEFAULT_HTTPX_POOL_TIMEOUT_SEC),
        )
    )
    return httpx.Timeout(connect=10.0, read=total_sec, write=total_sec, pool=pool)
