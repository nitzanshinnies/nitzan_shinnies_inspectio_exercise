"""Retry timeline — production must match `tests/reference_spec.py` (TESTS.md §4.2, PLAN.md §5)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain import retry as retry_mod
from tests import reference_spec as spec


@pytest.mark.unit
def test_delay_ms_matches_spec_for_each_failure_index() -> None:
    for k in range(0, 6):
        assert retry_mod.delay_ms_before_next_attempt_after_failure(
            k,
        ) == spec.delay_ms_before_next_attempt_after_failure(k)


@pytest.mark.unit
def test_next_due_at_matches_spec() -> None:
    assert retry_mod.next_due_at_ms_after_failure(1_000, 0) == spec.next_due_at_ms_after_failure(1_000, 0)
    assert retry_mod.next_due_at_ms_after_failure(1_000, 5) == spec.next_due_at_ms_after_failure(1_000, 5)


@pytest.mark.unit
def test_attempt_count_terminal_matches_spec() -> None:
    for n in (0, 1, 5, 6, 7, 99):
        assert retry_mod.attempt_count_is_terminal(n) == spec.attempt_count_is_terminal(n)


@pytest.mark.unit
def test_invalid_attempt_count_raises_value_error_like_spec() -> None:
    for bad in (-1, 6):
        with pytest.raises(ValueError):
            spec.delay_ms_before_next_attempt_after_failure(bad)
        with pytest.raises(ValueError):
            retry_mod.delay_ms_before_next_attempt_after_failure(bad)
