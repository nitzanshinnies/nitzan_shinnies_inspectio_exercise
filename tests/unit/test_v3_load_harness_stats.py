"""P7: pure load-harness stats."""

from __future__ import annotations

import pytest

from inspectio.v3.load_harness.stats import (
    HARD_GATE_RATIO_MIN,
    TARGET_GATE_RATIO_MIN,
    admission_rps,
    classify_throughput_gate,
    outcomes_visible_target,
    parse_positive_int_csv,
    percentile_sorted,
    split_parallel_counts,
    throughput_ratio,
)


@pytest.mark.unit
def test_parse_positive_int_csv_ok() -> None:
    assert parse_positive_int_csv("10") == (10,)
    assert parse_positive_int_csv(" 3 , 5 ") == (3, 5)


@pytest.mark.unit
def test_parse_positive_int_csv_rejects_empty_and_non_positive() -> None:
    with pytest.raises(ValueError, match="need at least one"):
        parse_positive_int_csv("", field_name="sizes")
    with pytest.raises(ValueError, match="must be >= 1"):
        parse_positive_int_csv("0", field_name="sizes")


@pytest.mark.unit
def test_percentile_sorted() -> None:
    s = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile_sorted(s, 0) == 10.0
    assert percentile_sorted(s, 50) == 30.0
    assert percentile_sorted(s, 100) == 50.0


@pytest.mark.unit
def test_split_parallel_counts() -> None:
    assert split_parallel_counts(7, 3) == [3, 2, 2]
    assert split_parallel_counts(5, 10) == [1, 1, 1, 1, 1]
    assert split_parallel_counts(1, 4) == [1]


@pytest.mark.unit
def test_admission_rps() -> None:
    assert admission_rps(100, 2.0) == 50.0
    assert admission_rps(10, 0.0) == 0.0


@pytest.mark.unit
def test_outcomes_visible_target() -> None:
    assert outcomes_visible_target(10, 100) == 10
    assert outcomes_visible_target(500, 100) == 100
    assert outcomes_visible_target(3, 50) == 3


@pytest.mark.unit
def test_throughput_ratio() -> None:
    assert throughput_ratio(85.0, 100.0) == 0.85
    assert throughput_ratio(10.0, 0.0) == 0.0


@pytest.mark.unit
def test_classify_throughput_gate() -> None:
    assert classify_throughput_gate(TARGET_GATE_RATIO_MIN) == "target_pass"
    assert classify_throughput_gate(HARD_GATE_RATIO_MIN) == "hard_pass_target_miss"
    assert classify_throughput_gate(0.69) == "hard_fail"
