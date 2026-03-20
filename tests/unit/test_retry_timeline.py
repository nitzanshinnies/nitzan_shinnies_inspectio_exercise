"""Retry timeline (plans/CORE_LIFECYCLE.md §4, TESTS.md §4.2)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain.retry import (
    attempt_count_is_terminal,
    delay_ms_before_next_attempt_after_failure,
    next_due_at_ms_after_failure,
)


@pytest.mark.unit
def test_delays_match_architect_timeline() -> None:
    assert delay_ms_before_next_attempt_after_failure(0) == 500
    assert delay_ms_before_next_attempt_after_failure(1) == 2_000
    assert delay_ms_before_next_attempt_after_failure(2) == 4_000
    assert delay_ms_before_next_attempt_after_failure(3) == 8_000
    assert delay_ms_before_next_attempt_after_failure(4) == 16_000


@pytest.mark.unit
def test_sixth_failed_attempt_has_no_retry_delay() -> None:
    assert delay_ms_before_next_attempt_after_failure(5) is None


@pytest.mark.unit
def test_next_due_at_adds_delay_to_now() -> None:
    assert next_due_at_ms_after_failure(1_000, 0) == 1_500
    assert next_due_at_ms_after_failure(1_000, 5) is None


@pytest.mark.unit
def test_attempt_count_terminal_threshold() -> None:
    assert attempt_count_is_terminal(6) is True
    assert attempt_count_is_terminal(5) is False
