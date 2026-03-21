"""Wakeup / due selection — production must match `tests/reference_spec.py` (TESTS.md §4.3)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain import wakeup as wakeup_mod
from tests import reference_spec as spec


@pytest.mark.unit
def test_tick_and_elapsed_round_trip_matches_spec() -> None:
    assert wakeup_mod.tick_count_for_elapsed_ms(5_000) == spec.tick_count_for_elapsed_ms(5_000)
    assert wakeup_mod.elapsed_ms_for_tick_count(10) == spec.elapsed_ms_for_tick_count(10)


@pytest.mark.unit
def test_select_due_matches_spec() -> None:
    messages = [("c", 200), ("a", 100), ("b", 100)]
    assert wakeup_mod.select_due_message_ids(messages, 250) == spec.select_due_message_ids(
        messages, 250
    )
    assert wakeup_mod.select_due_message_ids([("a", 500)], 400) == spec.select_due_message_ids(
        [("a", 500)], 400
    )


@pytest.mark.unit
def test_heap_pop_order_matches_spec() -> None:
    events = [(300, "late"), (100, "a"), (100, "b")]
    assert wakeup_mod.heap_pop_order(events) == spec.heap_pop_order(events)
