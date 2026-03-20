"""Worker bootstrap and resilience (TESTS.md §5.2, §5.4)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="TESTS.md §5.2: pending fixtures + heap scheduler")
def test_bootstrap_rebuilds_scheduler_from_pending() -> None:
    """Varied nextDueAt; min-heap-compatible due ordering."""


@pytest.mark.skip(reason="TESTS.md §5.2: malformed JSON in pending prefix")
def test_bootstrap_skips_malformed_pending_json() -> None:
    """No crash; optional metric."""


@pytest.mark.skip(reason="TESTS.md §5.4: inject transient persistence errors during scan")
def test_bootstrap_retries_transient_persistence_errors() -> None:
    """Bounded backoff; eventual completion."""
