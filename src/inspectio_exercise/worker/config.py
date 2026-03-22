"""Worker environment and tick / retry constants (plans/CORE_LIFECYCLE.md, SHARDING.md).

Full table and semantics: README.md **Worker env**.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from inspectio_exercise.common.http_client import HTTP_CLIENT_TIMEOUT_SEC

NOTIFICATION_PUBLISH_BASE_DELAY_SEC: float = float(
    os.environ.get("INSPECTIO_WORKER_NOTIFY_BACKOFF_SEC", "0.05"),
)
NOTIFICATION_PUBLISH_MAX_ATTEMPTS: int = int(os.environ.get("INSPECTIO_WORKER_NOTIFY_RETRIES", "3"))
OUTCOMES_HTTP_PATH: str = "/internal/v1/outcomes"
WORKER_ACTIVATE_PENDING_PATH: str = "/internal/v1/activate-pending"
PERSISTENCE_READ_BASE_DELAY_SEC: float = float(
    os.environ.get("INSPECTIO_WORKER_PERSISTENCE_READ_BACKOFF_SEC", "0.05"),
)
PERSISTENCE_READ_MAX_ATTEMPTS: int = int(
    os.environ.get("INSPECTIO_WORKER_PERSISTENCE_READ_RETRIES", "5"),
)
TERMINAL_LOOKBACK_HOURS: int = int(os.environ.get("INSPECTIO_WORKER_TERMINAL_LOOKBACK_HOURS", "6"))
WORKER_TICK_INTERVAL_SEC: float = float(os.environ.get("INSPECTIO_WORKER_TICK_SEC", "0.5"))
WORKER_MAX_PARALLEL_HANDLES: int = int(
    os.environ.get("INSPECTIO_WORKER_MAX_PARALLEL_HANDLES", "128"),
)

assert PERSISTENCE_READ_MAX_ATTEMPTS >= 1
assert TERMINAL_LOOKBACK_HOURS >= 0


@dataclass(frozen=True)
class WorkerSettings:
    hostname: str
    mock_sms_url: str
    notification_url: str
    persistence_url: str
    shards_per_pod: int
    total_shards: int
    http_timeout_sec: float
    max_parallel_handles: int = 128


def load_worker_settings() -> WorkerSettings:
    settings = WorkerSettings(
        hostname=os.environ.get("HOSTNAME", "worker-0"),
        mock_sms_url=os.environ.get("MOCK_SMS_URL", "http://127.0.0.1:8080"),
        notification_url=os.environ.get("NOTIFICATION_SERVICE_URL", "http://127.0.0.1:8002"),
        persistence_url=os.environ.get("PERSISTENCE_SERVICE_URL", "http://127.0.0.1:8001"),
        shards_per_pod=int(os.environ.get("SHARDS_PER_POD", "256")),
        total_shards=int(os.environ.get("TOTAL_SHARDS", "256")),
        http_timeout_sec=HTTP_CLIENT_TIMEOUT_SEC,
        max_parallel_handles=max(1, WORKER_MAX_PARALLEL_HANDLES),
    )
    if settings.total_shards <= 0 or settings.shards_per_pod <= 0:
        msg = (
            "TOTAL_SHARDS and SHARDS_PER_POD must be positive "
            f"(got total_shards={settings.total_shards!r}, "
            f"shards_per_pod={settings.shards_per_pod!r})"
        )
        raise ValueError(msg)
    return settings
