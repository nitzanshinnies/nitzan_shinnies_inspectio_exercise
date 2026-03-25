"""Environment-driven settings for the public REST API."""

from __future__ import annotations

import os

from inspectio_exercise.common.http_client import HTTP_CLIENT_TIMEOUT_SEC


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


PERSISTENCE_SERVICE_URL: str = os.environ.get("PERSISTENCE_SERVICE_URL", "http://127.0.0.1:8001")
NOTIFICATION_SERVICE_URL: str = os.environ.get("NOTIFICATION_SERVICE_URL", "http://127.0.0.1:8002")
TOTAL_SHARDS: int = int(os.environ.get("TOTAL_SHARDS", "256"))
# Comma-separated worker base URLs for POST /internal/v1/activate-pending (enqueue + wake scheduler).
INSPECTIO_WORKER_ACTIVATION_URLS: str = os.environ.get("INSPECTIO_WORKER_ACTIVATION_URLS", "")
WORKER_SHARDS_PER_POD_FOR_ACTIVATION: int = int(
    os.environ.get(
        "INSPECTIO_WORKER_SHARDS_PER_POD",
        os.environ.get("SHARDS_PER_POD", "256"),
    )
)
REPEAT_SUBMIT_PUT_BATCH_SIZE: int = max(
    1, int(os.environ.get("INSPECTIO_REPEAT_SUBMIT_PUT_BATCH_SIZE", "64"))
)
REPEAT_SUBMIT_PUT_MAX_CONCURRENCY: int = max(
    1, int(os.environ.get("INSPECTIO_REPEAT_SUBMIT_PUT_MAX_CONCURRENCY", "8"))
)
REPEAT_COUNT_MAX: int = int(os.environ.get("REPEAT_COUNT_MAX", "10000"))
OUTCOME_QUERY_LIMIT_DEFAULT: int = 100
OUTCOME_QUERY_LIMIT_MAX: int = 1000

# Public ``POST /messages`` body size cap (characters); ``413`` when exceeded (TEST_LIST TC-NM-07).
MESSAGE_BODY_MAX_CHARS: int = int(
    os.environ.get("INSPECTIO_MESSAGE_BODY_MAX_CHARS", str(256 * 1024))
)
assert MESSAGE_BODY_MAX_CHARS >= 1

# Outbound ``httpx`` clients to persistence + notification (same env as ``common.http_client``).
PEER_HTTP_CLIENT_TIMEOUT_SEC: float = HTTP_CLIENT_TIMEOUT_SEC

# Must match ``inspectio_exercise.worker.config`` paths.
WORKER_ACTIVATE_PENDING_HTTP_PATH: str = "/internal/v1/activate-pending"
WORKER_ACTIVATE_PENDING_BATCH_HTTP_PATH: str = "/internal/v1/activate-pending-batch"
WORKER_ACTIVATION_BATCH_MAX_KEYS: int = max(
    1, int(os.environ.get("INSPECTIO_WORKER_ACTIVATION_BATCH_MAX_KEYS", "512"))
)

# Default SMS `to` / body for public REST (plans/REST_API.md §3.1–3.2)
DEFAULT_MESSAGE_TO: str = "+10000000000"


def pending_ingest_via_redis_stream_enabled() -> bool:
    """When true, API stages pending bodies in Redis and a task flushes to persistence/S3."""
    return _env_flag("INSPECTIO_PENDING_INGEST_VIA_REDIS_STREAM")


def pending_stream_redis_url() -> str | None:
    return os.environ.get("INSPECTIO_PENDING_STREAM_REDIS_URL") or os.environ.get("REDIS_URL")
