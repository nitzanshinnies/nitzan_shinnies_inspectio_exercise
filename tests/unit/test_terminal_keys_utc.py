"""UTC terminal key paths (plans/PLAN.md §3, TESTS.md §4.4)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain.utc_paths import (
    terminal_failed_key,
    terminal_success_key,
    utc_segments_for_instant_ms,
)


@pytest.mark.unit
def test_utc_segments_zero_padded() -> None:
    # 2024-01-15 14:30:00 UTC
    ms = 1_705_329_000_000
    assert utc_segments_for_instant_ms(ms) == ("2024", "01", "15", "14")


@pytest.mark.unit
def test_year_rollover_utc() -> None:
    ms = 1_704_024_000_000  # 2023-12-31 12:00 UTC
    yyyy, mm, dd, hh = utc_segments_for_instant_ms(ms)
    assert yyyy == "2023"
    assert mm == "12"
    assert dd == "31"
    assert hh == "12"


@pytest.mark.unit
def test_success_key_shape() -> None:
    k = terminal_success_key("msg-1", 1_705_329_000_000)
    assert k.startswith("state/success/2024/01/15/14/msg-1.json")


@pytest.mark.unit
def test_failed_key_shape() -> None:
    k = terminal_failed_key("msg-1", 1_705_329_000_000)
    assert k.startswith("state/failed/2024/01/15/14/msg-1.json")
