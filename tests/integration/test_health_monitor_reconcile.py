"""Health monitor mock audit vs S3 (TESTS.md §5.6, HEALTH_MONITOR.md)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Skeleton: GET /healthz liveness only (TESTS.md §5.6)")
def test_health_monitor_healthz_no_full_reconcile() -> None:
    """2xx without expensive work."""


@pytest.mark.skip(reason="Skeleton: POST integrity-check reconciliation (TESTS.md §5.6)")
def test_integrity_check_post_matches_audit_to_s3() -> None:
    """Fixture or compose: mock audit + S3 map → ok / violations."""
