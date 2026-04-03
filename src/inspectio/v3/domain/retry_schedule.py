"""Absolute retry deadlines from initial arrival (receivedAtMs). See master plan §4.7."""

from __future__ import annotations

RETRY_OFFSETS_MS: tuple[int, ...] = (0, 500, 2000, 4000, 8000, 16000)

_ATTEMPT_MIN = 1
_ATTEMPT_MAX = 6


def all_attempt_deadlines_ms(
    received_at_ms: int,
) -> tuple[int, int, int, int, int, int]:
    return tuple(received_at_ms + offset for offset in RETRY_OFFSETS_MS)


def attempt_deadline_ms(received_at_ms: int, attempt_number_one_indexed: int) -> int:
    if (
        attempt_number_one_indexed < _ATTEMPT_MIN
        or attempt_number_one_indexed > _ATTEMPT_MAX
    ):
        msg = f"attempt_number_one_indexed must be in [{_ATTEMPT_MIN}, {_ATTEMPT_MAX}], got {attempt_number_one_indexed}"
        raise ValueError(msg)
    offset = RETRY_OFFSETS_MS[attempt_number_one_indexed - 1]
    return received_at_ms + offset
