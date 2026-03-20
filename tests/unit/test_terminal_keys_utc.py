"""S3 terminal keys and UTC partitions (TESTS.md §4.4, PLAN.md §3)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.skip(reason="Skeleton: success key path + status (TESTS.md §4.4)")
def test_success_move_and_json_status() -> None:
    """state/success/yyyy/MM/dd/hh/id.json; body status success."""


@pytest.mark.skip(reason="Skeleton: failed terminal key path + status (TESTS.md §4.4)")
def test_failed_terminal_move_and_json_status() -> None:
    """state/failed/...; body status failed."""


@pytest.mark.skip(reason="Skeleton: UTC segments for fixed instant (TESTS.md §4.4)")
def test_terminal_path_segments_match_utc_instant() -> None:
    """Inject clock; assert yyyy/MM/dd/hh from UTC."""
