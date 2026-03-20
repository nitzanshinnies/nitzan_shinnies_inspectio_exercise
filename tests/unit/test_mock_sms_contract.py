"""Mock SMS HTTP contract and audit (TESTS.md §4.6, MOCK_SMS.md)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.skip(reason="Skeleton: 2xx vs 5xx send outcomes (TESTS.md §4.6)")
def test_send_2xx_success_5xx_retry_path() -> None:
    """Worker treats any 5xx as failed send for lifecycle."""


@pytest.mark.skip(reason="Skeleton: shouldFail forces 5xx (MOCK_SMS §3)")
def test_should_fail_always_5xx() -> None:
    """Deterministic failure when shouldFail=true."""


@pytest.mark.skip(reason="Skeleton: audit row per POST /send (MOCK_SMS §8)")
def test_audit_row_per_handled_send() -> None:
    """JSONL / GET /audit/sends alignment."""
