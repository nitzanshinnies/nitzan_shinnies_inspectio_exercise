"""Persistence service + S3 simulation (TESTS.md §5.1)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="Skeleton: all I/O through persistence layer (TESTS.md §5.1)")
def test_reads_writes_via_persistence_service() -> None:
    """moto/file-backed; no ad-hoc S3 in app code under test."""


@pytest.mark.skip(reason="Skeleton: bootstrap list only owned prefixes (TESTS.md §5.1)")
def test_bootstrap_lists_only_owned_pending_prefixes() -> None:
    """Owned shard prefixes only."""
