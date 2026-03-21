"""Environment-driven settings for the public REST API."""

from __future__ import annotations

import os

PERSISTENCE_SERVICE_URL: str = os.environ.get("PERSISTENCE_SERVICE_URL", "http://127.0.0.1:8001")
NOTIFICATION_SERVICE_URL: str = os.environ.get("NOTIFICATION_SERVICE_URL", "http://127.0.0.1:8002")
TOTAL_SHARDS: int = int(os.environ.get("TOTAL_SHARDS", "256"))
REPEAT_COUNT_MAX: int = int(os.environ.get("REPEAT_COUNT_MAX", "10000"))
OUTCOME_QUERY_LIMIT_DEFAULT: int = 100
OUTCOME_QUERY_LIMIT_MAX: int = 1000
