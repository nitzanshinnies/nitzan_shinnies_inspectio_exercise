"""Shared defaults for outbound ``httpx`` clients to peer services."""

from __future__ import annotations

import os
from typing import Final

_DEFAULT_HTTP_CLIENT_TIMEOUT_SEC: Final[float] = 60.0

HTTP_CLIENT_TIMEOUT_SEC: float = float(
    os.environ.get(
        "INSPECTIO_HTTP_CLIENT_TIMEOUT_SEC",
        str(_DEFAULT_HTTP_CLIENT_TIMEOUT_SEC),
    ),
)
