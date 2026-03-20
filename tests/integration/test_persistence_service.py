"""Persistence service boundary (plans/TESTS.md §5.1).

Scenarios that need moto/LocalStack + real handlers stay skipped until implementation branch.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skip(reason="§5.1: all I/O via persistence HTTP; moto or file-backed backend")
def test_reads_writes_via_persistence_service_only() -> None:
    """No ad-hoc S3 client in code under test; spy on persistence boundary."""


@pytest.mark.skip(reason="§5.1: worker bootstrap list_prefix scoped to owned shard prefixes")
def test_bootstrap_lists_only_owned_pending_prefixes() -> None:
    """List/get only under state/pending/shard-<owned_shard_id>/ (RESILIENCE.md §3)."""
