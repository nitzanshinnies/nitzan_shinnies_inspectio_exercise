"""Unit tests for P12.9 WS3.1 rerun hygiene script."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "v3_p12_9_iter3_rerun_hygiene.py"
)


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "v3_p12_9_iter3_rerun_hygiene", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load rerun hygiene module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_parse_sustain_summary_line(tmp_path: Path) -> None:
    module = _load_module()
    log_file = tmp_path / "off.log"
    log_file.write_text(
        "[pod/x/load] SUSTAIN_SUMMARY admitted_total=12345 duration_sec=240.0 "
        "offered_admit_rps=51.44 concurrency=120 batch=200\n"
    )
    summary = module._parse_sustain_summary(log_file)
    assert summary["admitted_total"] == 12345
    assert summary["offered_admit_rps"] == 51.44
    assert summary["concurrency"] == 120


@pytest.mark.unit
def test_load_job_status_requires_single_success_zero_failed(tmp_path: Path) -> None:
    module = _load_module()
    payload = {"status": {"succeeded": 1, "failed": 0}}
    path = tmp_path / "job.json"
    path.write_text(json.dumps(payload))
    status = module._load_job_status(path)
    assert status["valid_single_attempt"] is True

    payload_bad = {"status": {"succeeded": 1, "failed": 1}}
    path.write_text(json.dumps(payload_bad))
    status_bad = module._load_job_status(path)
    assert status_bad["valid_single_attempt"] is False


@pytest.mark.unit
def test_series_metrics_counts_active_periods() -> None:
    module = _load_module()
    window = module.ProfileWindow(
        start_utc=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        end_utc=datetime(2026, 4, 1, 10, 4, tzinfo=UTC),
        query_start_utc=datetime(2026, 4, 1, 9, 59, tzinfo=UTC),
        query_end_utc=datetime(2026, 4, 1, 10, 6, tzinfo=UTC),
    )
    metrics = module._series_metrics(
        points_rps=[0.0, 12.0, 5.0, 0.0], window=window, period_sec=60
    )
    assert metrics["datapoints"] == 4
    assert metrics["active_periods"] == 2
    assert metrics["combined_avg_rps"] == pytest.approx(4.25)
