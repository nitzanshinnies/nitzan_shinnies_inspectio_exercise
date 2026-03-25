"""UTC terminal key paths — matches ``tests/reference_spec.py`` + PLAN.md §3."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_segments_for_instant_ms(instant_ms: int) -> tuple[str, str, str, str]:
    dt = datetime.fromtimestamp(instant_ms / 1000.0, tz=UTC)
    return (
        f"{dt.year:04d}",
        f"{dt.month:02d}",
        f"{dt.day:02d}",
        f"{dt.hour:02d}",
    )


def terminal_success_key(message_id: str, instant_ms: int) -> str:
    yyyy, mm, dd, hh = utc_segments_for_instant_ms(instant_ms)
    return f"state/success/{yyyy}/{mm}/{dd}/{hh}/{message_id}.json"


def terminal_failed_key(message_id: str, instant_ms: int) -> str:
    yyyy, mm, dd, hh = utc_segments_for_instant_ms(instant_ms)
    return f"state/failed/{yyyy}/{mm}/{dd}/{hh}/{message_id}.json"
