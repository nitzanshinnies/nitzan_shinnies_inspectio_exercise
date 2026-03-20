"""Worker bootstrap and resilience (plans/TESTS.md §5.2, §5.4, RESILIENCE.md)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="§5.2: seed pending keys + assert min-heap-compatible due order after bootstrap")
def test_bootstrap_rebuilds_scheduler_from_pending() -> None:
    """Varied nextDueAt; due work ordering."""


@pytest.mark.skip(reason="§5.2: malformed pending JSON skipped without crash")
def test_bootstrap_skips_malformed_pending_json() -> None:
    """Optional metric/log for invalid records."""


@pytest.mark.skip(reason="§5.4: inject transient persistence read failures; bounded retry then completion")
def test_bootstrap_retries_transient_persistence_errors() -> None:
    """RESILIENCE.md §5."""
