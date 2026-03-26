"""Pure schedule math for retry deadlines (§6.2)."""

from __future__ import annotations

RETRY_OFFSET_MS = (0, 500, 2_000, 4_000, 8_000, 16_000)
MIN_COMPLETED_SEND_COUNT = 0
MAX_COMPLETED_SEND_COUNT = len(RETRY_OFFSET_MS) - 1


def next_due_ms(arrival_ms: int, completed_send_count: int) -> int:
    """Return absolute due timestamp for the next send attempt.

    The schedule is anchored to the original ``arrival_ms`` per blueprint §6.2.
    ``completed_send_count`` is the number of completed sends before the next one.
    """
    if completed_send_count < MIN_COMPLETED_SEND_COUNT:
        msg = f"completed_send_count must be >= {MIN_COMPLETED_SEND_COUNT}"
        raise ValueError(msg)
    if completed_send_count > MAX_COMPLETED_SEND_COUNT:
        msg = f"completed_send_count must be <= {MAX_COMPLETED_SEND_COUNT}"
        raise ValueError(msg)
    return arrival_ms + RETRY_OFFSET_MS[completed_send_count]
