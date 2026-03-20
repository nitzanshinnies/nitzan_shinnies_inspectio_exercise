"""Health monitor: mock audit vs S3 (plans/TESTS.md §5.6, HEALTH_MONITOR.md).

Integrity POST stays skipped until reconciliation is implemented.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="§5.6: compose mock SMS + persistence + POST integrity-check; assert 2xx + body contract")
def test_integrity_check_post_resolves_audit_against_s3() -> None:
    """Deterministic scenario → ok; drift → non-2xx or violation JSON per HEALTH_MONITOR.md §4.2."""
