"""Persistence service boundary — no ad-hoc S3 from API/worker (TESTS.md §4.10)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.skip(reason="Skeleton: spy/fake persistence only I/O (TESTS.md §4.10)")
def test_api_uses_port_not_raw_client() -> None:
    """API modules under test call PersistencePort / HTTP client to persistence service."""


@pytest.mark.skip(reason="Skeleton: worker uses port not raw client (TESTS.md §4.10)")
def test_worker_uses_port_not_raw_client() -> None:
    """Worker modules under test call persistence boundary only."""
