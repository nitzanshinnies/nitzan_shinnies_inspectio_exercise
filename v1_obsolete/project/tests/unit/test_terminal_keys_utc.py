"""UTC terminal keys — production must match `tests/reference_spec.py` (TESTS.md §4.4, PLAN.md §3)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain import utc_paths as utc_mod
from tests import reference_spec as spec


@pytest.mark.unit
def test_utc_segments_match_spec() -> None:
    ms = 1_705_329_000_000
    assert utc_mod.utc_segments_for_instant_ms(ms) == spec.utc_segments_for_instant_ms(ms)


@pytest.mark.unit
def test_year_boundary_segments_match_spec() -> None:
    ms = 1_704_024_000_000
    assert utc_mod.utc_segments_for_instant_ms(ms) == spec.utc_segments_for_instant_ms(ms)


@pytest.mark.unit
def test_terminal_keys_match_spec() -> None:
    instant = 1_705_329_000_000
    mid = "msg-1"
    assert utc_mod.terminal_success_key(mid, instant) == spec.terminal_success_key(mid, instant)
    assert utc_mod.terminal_failed_key(mid, instant) == spec.terminal_failed_key(mid, instant)


@pytest.mark.unit
def test_failed_terminal_key_shares_partition_shape_with_success() -> None:
    """TC-PV-03: failed objects use the same UTC path layout as success."""
    instant = 1_705_329_000_000
    mid = "m"
    sk = utc_mod.terminal_success_key(mid, instant)
    fk = utc_mod.terminal_failed_key(mid, instant)
    assert sk.count("/") == fk.count("/")
    assert sk.startswith("state/success/")
    assert fk.startswith("state/failed/")
