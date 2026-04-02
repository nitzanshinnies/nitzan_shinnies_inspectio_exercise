"""P12.9 WS1 measurement lock helper logic tests."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest


def _load_module():
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "v3_p12_9_measurement_lock.py"
    )
    spec = importlib.util.spec_from_file_location("p12_9_measurement_lock", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_overlap_detector_flags_true_overlap() -> None:
    module = _load_module()
    q1 = module.QueryWindow(
        profile="off",
        run_id="r1",
        job_start_utc=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        job_end_utc=datetime(2026, 1, 1, 0, 1, 0, tzinfo=UTC),
        query_start_utc=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        query_end_utc=datetime(2026, 1, 1, 0, 2, 0, tzinfo=UTC),
    )
    q2 = module.QueryWindow(
        profile="on",
        run_id="r1",
        job_start_utc=datetime(2026, 1, 1, 0, 1, 0, tzinfo=UTC),
        job_end_utc=datetime(2026, 1, 1, 0, 2, 0, tzinfo=UTC),
        query_start_utc=datetime(2026, 1, 1, 0, 1, 59, tzinfo=UTC),
        query_end_utc=datetime(2026, 1, 1, 0, 3, 0, tzinfo=UTC),
    )
    overlaps = module._find_query_window_overlaps([q1, q2])
    assert overlaps == [("r1-off", "r1-on")]


@pytest.mark.unit
def test_overlap_detector_allows_touching_windows() -> None:
    module = _load_module()
    q1 = module.QueryWindow(
        profile="off",
        run_id="r1",
        job_start_utc=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        job_end_utc=datetime(2026, 1, 1, 0, 1, 0, tzinfo=UTC),
        query_start_utc=datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        query_end_utc=datetime(2026, 1, 1, 0, 2, 0, tzinfo=UTC),
    )
    q2 = module.QueryWindow(
        profile="on",
        run_id="r1",
        job_start_utc=datetime(2026, 1, 1, 0, 2, 0, tzinfo=UTC),
        job_end_utc=datetime(2026, 1, 1, 0, 3, 0, tzinfo=UTC),
        query_start_utc=datetime(2026, 1, 1, 0, 2, 0, tzinfo=UTC),
        query_end_utc=datetime(2026, 1, 1, 0, 4, 0, tzinfo=UTC),
    )
    assert module._find_query_window_overlaps([q1, q2]) == []


@pytest.mark.unit
def test_peak_metric_requires_explicit_flag() -> None:
    module = _load_module()
    with pytest.raises(
        ValueError, match="combined_peak_rps cannot be used as sole gate metric"
    ):
        module._validate_gate_metric(
            repro_metric="combined_peak_rps", allow_peak_gate=False
        )
    module._validate_gate_metric(repro_metric="combined_peak_rps", allow_peak_gate=True)
    module._validate_gate_metric(repro_metric="combined_avg_rps", allow_peak_gate=False)


@pytest.mark.unit
def test_variance_calculator_deterministic() -> None:
    module = _load_module()
    variance = module._variance_percent(100.0, 80.0)
    assert round(variance, 6) == 22.222222
