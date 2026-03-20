"""S3 object keys for ``state/notifications/...`` (NOTIFICATION_SERVICE.md §3)."""

from __future__ import annotations

from datetime import datetime, timezone


def utc_segments_for_instant_ms(instant_ms: int) -> tuple[str, str, str, str]:
    dt = datetime.fromtimestamp(instant_ms / 1000.0, tz=timezone.utc)
    return (
        f"{dt.year:04d}",
        f"{dt.month:02d}",
        f"{dt.day:02d}",
        f"{dt.hour:02d}",
    )


def notification_object_key(notification_id: str, recorded_at_ms: int) -> str:
    yyyy, mm, dd, hh = utc_segments_for_instant_ms(recorded_at_ms)
    return f"state/notifications/{yyyy}/{mm}/{dd}/{hh}/{notification_id}.json"
