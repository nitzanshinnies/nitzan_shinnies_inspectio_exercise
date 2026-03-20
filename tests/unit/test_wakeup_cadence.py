"""Wakeup loop: due selection, ordering, 500ms cadence (TESTS.md §4.3)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.skip(reason="Skeleton: nextDueAt <= T eligibility (TESTS.md §4.3)")
def test_only_due_messages_selected_on_tick() -> None:
    """Inject clock; assert eligibility."""


@pytest.mark.skip(reason="Skeleton: earliest nextDueAt first (TESTS.md §4.3)")
def test_due_ordering_min_heap_compatible() -> None:
    """Min-heap ordering for due work."""


@pytest.mark.skip(reason="Skeleton: 500ms tick vs simulated time (TESTS.md §4.3)")
def test_wakeup_cadence_500ms() -> None:
    """Tick count ↔ elapsed time (e.g. 10 ticks ⇒ 5s)."""
