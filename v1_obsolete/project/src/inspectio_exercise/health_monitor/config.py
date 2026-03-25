"""Environment-driven settings for the health monitor (plans/HEALTH_MONITOR.md §3–§5)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from inspectio_exercise.common.http_client import HTTP_CLIENT_TIMEOUT_SEC
from inspectio_exercise.mock_sms import config as mock_sms_config


@dataclass(frozen=True)
class HealthMonitorSettings:
    # Mock ``GET /audit/sends`` limit (typically ``mock_sms.config.AUDIT_SENDS_MAX_LIMIT``).
    audit_fetch_limit: int
    default_grace_ms: int
    enable_periodic_reconcile: bool
    http_timeout_sec: float
    integrity_check_token: str | None
    mock_sms_url: str
    persistence_url: str
    poll_interval_sec: float


DEFAULT_GRACE_MS: int = 500
HEADER_INTEGRITY_CHECK_TOKEN: str = "X-Integrity-Check-Token"
DEFAULT_POLL_INTERVAL_SEC: float = 60.0


def load_health_monitor_settings() -> HealthMonitorSettings:
    """Load settings from environment (see HEALTH_MONITOR.md §7 checklist)."""
    persistence_url = os.environ.get(
        "PERSISTENCE_SERVICE_URL",
        "http://127.0.0.1:8001",
    )
    mock_sms_url = os.environ.get("MOCK_SMS_URL", "http://127.0.0.1:8080")
    raw_token = os.environ.get("INTEGRITY_CHECK_TOKEN", "").strip()
    token = raw_token or None
    grace = int(os.environ.get("HEALTH_MONITOR_DEFAULT_GRACE_MS", str(DEFAULT_GRACE_MS)))
    enable_periodic = os.environ.get("ENABLE_PERIODIC_RECONCILE", "").lower() in (
        "1",
        "true",
        "yes",
    )
    poll = float(
        os.environ.get(
            "HEALTH_MONITOR_POLL_INTERVAL_SEC",
            str(DEFAULT_POLL_INTERVAL_SEC),
        )
    )
    return HealthMonitorSettings(
        audit_fetch_limit=mock_sms_config.AUDIT_SENDS_MAX_LIMIT,
        default_grace_ms=grace,
        enable_periodic_reconcile=enable_periodic,
        http_timeout_sec=HTTP_CLIENT_TIMEOUT_SEC,
        integrity_check_token=token,
        mock_sms_url=mock_sms_url.rstrip("/"),
        persistence_url=persistence_url.rstrip("/"),
        poll_interval_sec=poll,
    )
