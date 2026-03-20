"""Worker bootstrap and resilience (TESTS.md §5.2, RESILIENCE.md)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Skeleton: restore due work from nextDueAt (TESTS.md §5.2)")
def test_bootstrap_rebuilds_scheduler_from_pending() -> None:
    """Varied nextDueAt; min-heap order."""


@pytest.mark.skip(reason="Skeleton: malformed pending skipped (TESTS.md §5.2)")
def test_bootstrap_skips_malformed_pending_json() -> None:
    """No crash; optional metric."""


@pytest.mark.skip(reason="Skeleton: transient read retry during bootstrap (TESTS.md §5.4)")
def test_bootstrap_retries_transient_persistence_errors() -> None:
    """Bounded backoff; eventual completion."""
