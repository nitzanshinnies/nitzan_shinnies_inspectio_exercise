"""Retry delays and attempt-count rules — matches ``tests/reference_spec.py`` + PLAN.md §5."""

from __future__ import annotations


def attempt_count_is_terminal(attempt_count: int) -> bool:
    """Pending record is terminal failed only when ``attemptCount == 6`` (PLAN.md §5)."""
    return attempt_count == 6


def delay_ms_before_next_attempt_after_failure(attempt_count_when_failed: int) -> int | None:
    """After a failed send, ``attemptCount`` was ``attempt_count_when_failed`` (0..5)."""
    if attempt_count_when_failed < 0 or attempt_count_when_failed > 5:
        raise ValueError("attempt_count_when_failed must be in 0..5")
    if attempt_count_when_failed == 5:
        return None
    delays = (500, 2_000, 4_000, 8_000, 16_000)
    return delays[attempt_count_when_failed]


def next_due_at_ms_after_failure(now_ms: int, attempt_count_when_failed: int) -> int | None:
    delay = delay_ms_before_next_attempt_after_failure(attempt_count_when_failed)
    if delay is None:
        return None
    return now_ms + delay


# Recent-outcomes API / assignment brief — human-readable terminal failure line.
BRIEF_REASON_TERMINAL_AFTER_SIX_FAILURES: str = "discarded after six failed send attempts"
