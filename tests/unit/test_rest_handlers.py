"""REST API validation and contracts (TESTS.md §4.7, REST_API.md)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.skip(reason="Skeleton: POST /messages validation (TESTS.md §4.7)")
def test_post_messages_rejects_invalid_body() -> None:
    """Empty/malformed to/body → 4xx with stable error shape."""


@pytest.mark.skip(reason="Skeleton: POST /messages/repeat count bounds (TESTS.md §4.7)")
def test_post_messages_repeat_count_validation() -> None:
    """Invalid count rejected; upper bound enforced."""


@pytest.mark.skip(reason="Skeleton: GET outcomes limit validation (TESTS.md §4.7)")
def test_get_outcomes_limit_validation() -> None:
    """Invalid limit → 4xx; default 100 when omitted."""
