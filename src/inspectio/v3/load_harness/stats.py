"""Pure stats for load driver (unit-tested)."""

from __future__ import annotations


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
