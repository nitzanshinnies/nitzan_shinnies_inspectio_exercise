"""P1 domain schedule tests (TC-DOM-*)."""

from __future__ import annotations

import pytest

from inspectio.domain.schedule import (
    RETRY_OFFSET_MS,
    is_send_due,
    next_due_ms,
)

ARRIVAL_MS = 1_700_000_000_000


@pytest.mark.unit
def test_retry_offset_tuple_matches_section_6_2() -> None:
    assert RETRY_OFFSET_MS == (0, 500, 2_000, 4_000, 8_000, 16_000)


@pytest.mark.unit
def test_next_due_first_send_matches_arrival_tc_dom_001() -> None:
    assert next_due_ms(ARRIVAL_MS, 0) == ARRIVAL_MS


@pytest.mark.unit
def test_next_due_before_second_send_tc_dom_002() -> None:
    assert next_due_ms(ARRIVAL_MS, 1) == ARRIVAL_MS + 500


@pytest.mark.unit
@pytest.mark.parametrize(
    ("completed_send_count", "expected_due_ms"),
    [
        (2, ARRIVAL_MS + 2_000),
        (3, ARRIVAL_MS + 4_000),
        (4, ARRIVAL_MS + 8_000),
        (5, ARRIVAL_MS + 16_000),
    ],
    ids=[
        "tc_dom_003_count_2",
        "tc_dom_003_count_3",
        "tc_dom_003_count_4",
        "tc_dom_003_count_5",
    ],
)
def test_next_due_matches_section_6_2_rows_tc_dom_003(
    completed_send_count: int,
    expected_due_ms: int,
) -> None:
    assert next_due_ms(ARRIVAL_MS, completed_send_count) == expected_due_ms


@pytest.mark.unit
def test_no_seventh_send_schedule_after_fifth_completed_tc_dom_004() -> None:
    with pytest.raises(ValueError):
        next_due_ms(ARRIVAL_MS, 6)


@pytest.mark.unit
def test_due_boundary_now_before_due_must_not_dispatch_tc_dom_007() -> None:
    next_due_at_ms = next_due_ms(ARRIVAL_MS, 4)
    now_ms = next_due_at_ms - 1
    assert not is_send_due(now_ms, next_due_at_ms)


@pytest.mark.unit
def test_due_boundary_now_equal_due_may_dispatch_tc_dom_008() -> None:
    next_due_at_ms = next_due_ms(ARRIVAL_MS, 4)
    now_ms = next_due_at_ms
    assert is_send_due(now_ms, next_due_at_ms)
