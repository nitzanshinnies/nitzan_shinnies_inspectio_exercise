"""Environment-driven settings for the notification service."""

from __future__ import annotations

import os

OUTCOMES_STORE_BACKEND: str = os.environ.get("OUTCOMES_STORE_BACKEND", "redis")
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
PERSISTENCE_SERVICE_URL: str = os.environ.get("PERSISTENCE_SERVICE_URL", "http://127.0.0.1:8001")
HYDRATION_MAX: int = int(os.environ.get("HYDRATION_MAX", "10000"))
OUTCOMES_STREAM_MAX: int = int(os.environ.get("OUTCOMES_STREAM_MAX", str(HYDRATION_MAX)))
REDIS_KEY_SUCCESS: str = "outcomes:success"
REDIS_KEY_FAILED: str = "outcomes:failed"
QUERY_LIMIT_DEFAULT: int = 100
QUERY_LIMIT_MAX: int = 1000
