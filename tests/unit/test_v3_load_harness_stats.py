"""P7: pure load-harness stats."""

from __future__ import annotations

import pytest

from inspectio.v3.load_harness.stats import (
    HARD_GATE_RATIO_MIN,
    TARGET_GATE_RATIO_MIN,
    admission_rps,
    classify_composite_throughput_gate,
    classify_throughput_gate,
    COMPLETION_HARD_GATE_RATIO_MIN,
    COMPLETION_TARGET_GATE_RATIO_MIN,
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


@pytest.mark.unit
def test_composite_gate_hard_fail_completion() -> None:
    result = classify_composite_throughput_gate(
        admission_ratio=0.9,
        completion_ratio=0.6,
        writer_lag_on_ms=1000.0,
        writer_lag_cap_ms=5000.0,
        flush_latency_on_ms=50.0,
        flush_latency_cap_ms=500.0,
        crash_loop_off=False,
        crash_loop_on=False,
    )
    assert result["classification"] == "hard_fail_completion"


@pytest.mark.unit
def test_composite_gate_hard_fail_stability() -> None:
    result = classify_composite_throughput_gate(
        admission_ratio=0.9,
        completion_ratio=0.9,
        writer_lag_on_ms=9000.0,
        writer_lag_cap_ms=5000.0,
        flush_latency_on_ms=50.0,
        flush_latency_cap_ms=500.0,
        crash_loop_off=False,
        crash_loop_on=False,
    )
    assert result["classification"] == "hard_fail_stability"


@pytest.mark.unit
def test_composite_gate_hard_fail_admission() -> None:
    result = classify_composite_throughput_gate(
        admission_ratio=0.6,
        completion_ratio=0.9,
        writer_lag_on_ms=1000.0,
        writer_lag_cap_ms=5000.0,
        flush_latency_on_ms=50.0,
        flush_latency_cap_ms=500.0,
        crash_loop_off=False,
        crash_loop_on=False,
    )
    assert result["classification"] == "hard_fail_admission"


@pytest.mark.unit
def test_composite_gate_target_pass() -> None:
    result = classify_composite_throughput_gate(
        admission_ratio=TARGET_GATE_RATIO_MIN,
        completion_ratio=COMPLETION_TARGET_GATE_RATIO_MIN,
        writer_lag_on_ms=1000.0,
        writer_lag_cap_ms=5000.0,
        flush_latency_on_ms=50.0,
        flush_latency_cap_ms=500.0,
        crash_loop_off=False,
        crash_loop_on=False,
    )
    assert result["classification"] == "target_pass"


@pytest.mark.unit
def test_composite_gate_hard_pass_target_miss() -> None:
    result = classify_composite_throughput_gate(
        admission_ratio=TARGET_GATE_RATIO_MIN,
        completion_ratio=COMPLETION_HARD_GATE_RATIO_MIN,
        writer_lag_on_ms=1000.0,
        writer_lag_cap_ms=5000.0,
        flush_latency_on_ms=50.0,
        flush_latency_cap_ms=500.0,
        crash_loop_off=False,
        crash_loop_on=False,
    )
    assert result["classification"] == "hard_pass_target_miss"


@pytest.mark.unit
def test_composite_gate_invalid_missing_metrics() -> None:
    result = classify_composite_throughput_gate(
        admission_ratio=0.9,
        completion_ratio=None,
        writer_lag_on_ms=1000.0,
        writer_lag_cap_ms=5000.0,
        flush_latency_on_ms=50.0,
        flush_latency_cap_ms=500.0,
        crash_loop_off=False,
        crash_loop_on=False,
    )
    assert result["classification"] == "invalid_missing_metrics"
