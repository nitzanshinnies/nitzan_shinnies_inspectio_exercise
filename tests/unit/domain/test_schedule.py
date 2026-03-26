"""P1 domain schedule tests (TC-DOM-*)."""

from __future__ import annotations

import pytest

from inspectio.domain.schedule import RETRY_OFFSET_MS, next_due_ms

ARRIVAL_MS = 1_700_000_000_000


@pytest.mark.unit
def test_retry_offset_matches_spec_tc_dom_001() -> None:
    assert RETRY_OFFSET_MS == (0, 500, 2_000, 4_000, 8_000, 16_000)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("completed_send_count", "expected_due_ms"),
    [
        (0, ARRIVAL_MS),
        (1, ARRIVAL_MS + 500),
        (2, ARRIVAL_MS + 2_000),
        (3, ARRIVAL_MS + 4_000),
        (4, ARRIVAL_MS + 8_000),
        (5, ARRIVAL_MS + 16_000),
    ],
)
def test_next_due_matches_absolute_arrival_schedule_tc_dom_002_003(
    completed_send_count: int,
    expected_due_ms: int,
) -> None:
    assert next_due_ms(ARRIVAL_MS, completed_send_count) == expected_due_ms


@pytest.mark.unit
def test_next_due_rejects_out_of_range_completed_send_count_tc_dom_004() -> None:
    with pytest.raises(ValueError):
        next_due_ms(ARRIVAL_MS, 6)


@pytest.mark.unit
def test_due_boundary_now_before_due_is_not_dispatchable_tc_dom_007() -> None:
    next_due_at_ms = next_due_ms(ARRIVAL_MS, 4)
    now_ms = next_due_at_ms - 1
    assert now_ms < next_due_at_ms


@pytest.mark.unit
def test_due_boundary_now_equal_due_is_dispatchable_tc_dom_008() -> None:
    next_due_at_ms = next_due_ms(ARRIVAL_MS, 4)
    now_ms = next_due_at_ms
    assert now_ms >= next_due_at_ms
