"""UTC date-partition segments for terminal S3 keys (plans/PLAN.md §3)."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_segments_for_instant_ms(instant_ms: int) -> tuple[str, str, str, str]:
    """Return `(yyyy, MM, dd, hh)` in UTC for terminal key paths."""
    dt = datetime.fromtimestamp(instant_ms / 1000.0, tz=timezone.utc)
    return (
        f"{dt.year:04d}",
        f"{dt.month:02d}",
        f"{dt.day:02d}",
        f"{dt.hour:02d}",
    )


def terminal_failed_key(message_id: str, instant_ms: int) -> str:
    """`state/failed/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`."""
    yyyy, mm, dd, hh = utc_segments_for_instant_ms(instant_ms)
    return f"state/failed/{yyyy}/{mm}/{dd}/{hh}/{message_id}.json"


def terminal_success_key(message_id: str, instant_ms: int) -> str:
    """`state/success/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`."""
    yyyy, mm, dd, hh = utc_segments_for_instant_ms(instant_ms)
    return f"state/success/{yyyy}/{mm}/{dd}/{hh}/{message_id}.json"
