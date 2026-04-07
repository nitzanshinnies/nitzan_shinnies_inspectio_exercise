"""Pure stats for load driver (unit-tested)."""

from __future__ import annotations

HARD_GATE_RATIO_MIN = 0.70
TARGET_GATE_RATIO_MIN = 0.85
COMPLETION_HARD_GATE_RATIO_MIN = 0.70
COMPLETION_TARGET_GATE_RATIO_MIN = 0.85


def parse_positive_int_csv(raw: str, *, field_name: str = "value") -> tuple[int, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        msg = f"need at least one comma-separated {field_name}"
        raise ValueError(msg)
    out: list[int] = []
    for p in parts:
        v = int(p, 10)
        if v < 1:
            msg = f"{field_name} must be >= 1, got {v}"
            raise ValueError(msg)
        out.append(v)
    return tuple(out)


def percentile_sorted(sorted_ms: list[float], p: float) -> float:
    if not sorted_ms:
        return 0.0
    if p <= 0:
        return sorted_ms[0]
    if p >= 100:
        return sorted_ms[-1]
    k = max(0, min(len(sorted_ms) - 1, int(round((p / 100.0) * (len(sorted_ms) - 1)))))
    return sorted_ms[k]


def split_parallel_counts(total: int, parallel: int) -> list[int]:
    if total < 1:
        return []
    if parallel < 1:
        parallel = 1
    if parallel == 1:
        return [total]
    parallel = min(parallel, total)
    base = total // parallel
    rem = total % parallel
    return [base + (1 if i < rem else 0) for i in range(parallel)]


def admission_rps(total_recipients: int, wall_sec: float) -> float:
    if wall_sec <= 0:
        return 0.0
    return round(total_recipients / wall_sec, 2)


def outcomes_visible_target(expected_recipients: int, api_limit: int) -> int:
    """How many success rows we need in one GET (cap ``api_limit``, usually 100)."""
    if expected_recipients < 1:
        return 0
    cap = max(1, min(api_limit, 100))
    return min(expected_recipients, cap)


def throughput_ratio(persist_on_rps: float, persist_off_rps: float) -> float:
    if persist_off_rps <= 0:
        return 0.0
    return round(persist_on_rps / persist_off_rps, 4)


def classify_throughput_gate(
    ratio: float,
    *,
    hard_gate: float = HARD_GATE_RATIO_MIN,
    target_gate: float = TARGET_GATE_RATIO_MIN,
) -> str:
    if ratio >= target_gate:
        return "target_pass"
    if ratio >= hard_gate:
        return "hard_pass_target_miss"
    return "hard_fail"


def classify_composite_throughput_gate(
    *,
    admission_ratio: float | None,
    completion_ratio: float | None,
    writer_lag_on_ms: float | None,
    writer_lag_cap_ms: float | None,
    flush_latency_on_ms: float | None,
    flush_latency_cap_ms: float | None,
    crash_loop_off: bool | None,
    crash_loop_on: bool | None,
    admission_hard: float = HARD_GATE_RATIO_MIN,
    admission_target: float = TARGET_GATE_RATIO_MIN,
    completion_hard: float = COMPLETION_HARD_GATE_RATIO_MIN,
    completion_target: float = COMPLETION_TARGET_GATE_RATIO_MIN,
) -> dict[str, object]:
    required_values = (
        admission_ratio,
        completion_ratio,
        writer_lag_on_ms,
        writer_lag_cap_ms,
        flush_latency_on_ms,
        flush_latency_cap_ms,
        crash_loop_off,
        crash_loop_on,
    )
    if any(value is None for value in required_values):
        return {
            "classification": "invalid_missing_metrics",
            "admission_hard_pass": False,
            "admission_target_pass": False,
            "completion_hard_pass": False,
            "completion_target_pass": False,
            "writer_lag_cap_pass": False,
            "flush_latency_cap_pass": False,
            "crash_loop_pass": False,
        }

    assert admission_ratio is not None
    assert completion_ratio is not None
    assert writer_lag_on_ms is not None
    assert writer_lag_cap_ms is not None
    assert flush_latency_on_ms is not None
    assert flush_latency_cap_ms is not None
    assert crash_loop_off is not None
    assert crash_loop_on is not None

    admission_hard_pass = admission_ratio >= admission_hard
    admission_target_pass = admission_ratio >= admission_target
    completion_hard_pass = completion_ratio >= completion_hard
    completion_target_pass = completion_ratio >= completion_target
    writer_lag_cap_pass = writer_lag_on_ms <= writer_lag_cap_ms
    flush_latency_cap_pass = flush_latency_on_ms <= flush_latency_cap_ms
    crash_loop_pass = (not crash_loop_off) and (not crash_loop_on)

    if not completion_hard_pass:
        classification = "hard_fail_completion"
    elif not admission_hard_pass:
        classification = "hard_fail_admission"
    elif not (writer_lag_cap_pass and flush_latency_cap_pass and crash_loop_pass):
        classification = "hard_fail_stability"
    elif admission_target_pass and completion_target_pass:
        classification = "target_pass"
    else:
        classification = "hard_pass_target_miss"

    return {
        "classification": classification,
        "admission_hard_pass": admission_hard_pass,
        "admission_target_pass": admission_target_pass,
        "completion_hard_pass": completion_hard_pass,
        "completion_target_pass": completion_target_pass,
        "writer_lag_cap_pass": writer_lag_cap_pass,
        "flush_latency_cap_pass": flush_latency_cap_pass,
        "crash_loop_pass": crash_loop_pass,
    }
