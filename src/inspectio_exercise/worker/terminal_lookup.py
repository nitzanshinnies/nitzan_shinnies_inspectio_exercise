"""Locate existing terminal objects for idempotent worker transitions (CORE_LIFECYCLE.md §6.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from inspectio_exercise.domain.utc_paths import utc_segments_for_instant_ms


def terminal_prefixes_for_lookback(
    *,
    lookback_hours: int,
    now_ms: int,
    tree_root: str,
) -> list[str]:
    """Return ``list_prefix`` prefixes covering ``tree_root`` for ``now_ms`` and prior UTC hours."""
    dt = datetime.fromtimestamp(now_ms / 1000.0, tz=UTC)
    prefixes: list[str] = []
    for i in range(max(0, lookback_hours) + 1):
        t = dt - timedelta(hours=i)
        instant_ms = int(t.timestamp() * 1000)
        yyyy, mm, dd, hh = utc_segments_for_instant_ms(instant_ms)
        prefixes.append(f"{tree_root}/{yyyy}/{mm}/{dd}/{hh}/")
    return prefixes


def key_matches_message_terminal(key: str, message_id: str) -> bool:
    return key.endswith(f"/{message_id}.json")
