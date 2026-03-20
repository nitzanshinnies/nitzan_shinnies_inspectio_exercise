"""Wakeup / due selection (plans/CORE_LIFECYCLE.md §4.3, TESTS.md §4.3)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain.wakeup import (
    elapsed_ms_for_tick_count,
    heap_pop_order,
    select_due_message_ids,
    tick_count_for_elapsed_ms,
)


@pytest.mark.unit
def test_tick_count_matches_elapsed() -> None:
    assert tick_count_for_elapsed_ms(5_000) == 10
    assert elapsed_ms_for_tick_count(10) == 5_000


@pytest.mark.unit
def test_select_due_ordered_by_next_due_then_id() -> None:
    messages = [("c", 200), ("a", 100), ("b", 100)]
    assert select_due_message_ids(messages, 250) == ["a", "b", "c"]


@pytest.mark.unit
def test_not_due_excluded() -> None:
    assert select_due_message_ids([("a", 500)], 400) == []


@pytest.mark.unit
def test_heap_pop_order_is_earliest_first() -> None:
    events = [(300, "late"), (100, "a"), (100, "b")]
    assert heap_pop_order(events) == ["a", "b", "late"]
