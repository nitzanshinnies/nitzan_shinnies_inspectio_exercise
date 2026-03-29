"""P0: retry deadlines absolute from receivedAtMs (master plan §4.7)."""

from __future__ import annotations

import pytest

from inspectio.v3.domain.retry_schedule import (
    RETRY_OFFSETS_MS,
    all_attempt_deadlines_ms,
    attempt_deadline_ms,
)


@pytest.mark.unit
def test_retry_offsets_match_master_plan_table() -> None:
    assert RETRY_OFFSETS_MS == (0, 500, 2000, 4000, 8000, 16000)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("attempt_1_indexed", "expected_offset_ms"),
    [
        (1, 0),
        (2, 500),
        (3, 2000),
        (4, 4000),
        (5, 8000),
        (6, 16000),
    ],
)
def test_attempt_deadline_ms_table(
    attempt_1_indexed: int, expected_offset_ms: int
) -> None:
    received_at_ms = 1_704_000_000_000
    assert (
        attempt_deadline_ms(received_at_ms, attempt_1_indexed)
        == received_at_ms + expected_offset_ms
    )


@pytest.mark.unit
def test_all_attempt_deadlines_ms_returns_six_values() -> None:
    base = 42
    assert all_attempt_deadlines_ms(base) == (
        42,
        542,
        2042,
        4042,
        8042,
        16042,
    )


@pytest.mark.unit
@pytest.mark.parametrize("bad", [0, 7, -1])
def test_attempt_deadline_ms_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(ValueError):
        attempt_deadline_ms(0, bad)
