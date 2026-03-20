"""Health monitor: mock audit vs S3 (TESTS.md §5.6, HEALTH_MONITOR.md)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_integrity_check_post_stub_501(health_monitor_client) -> None:
    """POST /internal/v1/integrity-check not implemented (skeleton)."""
    response = health_monitor_client.post("/internal/v1/integrity-check")
    assert response.status_code == 501


@pytest.mark.skip(reason="TESTS.md §5.6: fixture audit JSON + S3 object map reconciliation")
def test_integrity_check_post_matches_audit_to_s3() -> None:
    """Compose or fixtures: deterministic scenario → ok / violation JSON."""
