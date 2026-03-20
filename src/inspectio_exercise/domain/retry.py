"""Retry delays and attempt-count rules (plans/CORE_LIFECYCLE.md §4, PLAN.md §5)."""

from __future__ import annotations

# After failure at attemptCount 0..4, delay before the next attempt (attempt #2 .. #6).
# After failure at attemptCount 5 (6th attempt failed), transition to terminal failed — no delay.
_RETRY_DELAY_MS: tuple[int, ...] = (500, 2_000, 4_000, 8_000, 16_000)


def attempt_count_is_terminal(attempt_count: int) -> bool:
    """Terminal failed in pending when `attempt_count == 6` (PLAN.md §5)."""
    return attempt_count >= 6


def delay_ms_before_next_attempt_after_failure(attempt_count_when_failed: int) -> int | None:
    """
    After a failed send, `attempt_count` was `attempt_count_when_failed` (0..5).

    Returns milliseconds to wait before the next attempt, or ``None`` if the next
    state is terminal failure (after the 6th failed attempt, i.e. failed at count 5).
    """
    if attempt_count_when_failed < 0 or attempt_count_when_failed > 5:
        raise ValueError("attempt_count_when_failed must be in 0..5 for a retryable failure")
    if attempt_count_when_failed == 5:
        return None
    return _RETRY_DELAY_MS[attempt_count_when_failed]


def next_due_at_ms_after_failure(now_ms: int, attempt_count_when_failed: int) -> int | None:
    """`now_ms + delay` for the next retry, or ``None`` if terminal."""
    delay = delay_ms_before_next_attempt_after_failure(attempt_count_when_failed)
    if delay is None:
        return None
    return now_ms + delay
