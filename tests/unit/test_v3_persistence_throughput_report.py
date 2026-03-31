"""P12.7: throughput report script validation and rendering tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _write_phase_json(path: Path, *, rps: float, mode: str) -> None:
    payload = {
        "ok": True,
        "phases": [
            {
                "recipients_admitted": 10_000,
                "admission_rps": rps,
                "persistence_mode": mode,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _base_args(tmp_path: Path) -> list[str]:
    off = tmp_path / "off.json"
    on = tmp_path / "on.json"
    _write_phase_json(off, rps=1000.0, mode="off")
    _write_phase_json(on, rps=900.0, mode="on")
    return [
        sys.executable,
        "scripts/v3_persistence_throughput_report.py",
        "--persist-off-json",
        str(off),
        "--persist-on-json",
        str(on),
        "--persist-off-delete-rps",
        "100",
        "--persist-on-delete-rps",
        "90",
        "--persist-off-writer-lag-ms",
        "0",
        "--persist-on-writer-lag-ms",
        "1000",
        "--persist-off-error-rate",
        "0.0",
        "--persist-on-error-rate",
        "0.01",
        "--persist-off-window",
        "2026-01-01T00:00:00Z..2026-01-01T00:05:00Z",
        "--persist-on-window",
        "2026-01-01T00:10:00Z..2026-01-01T00:15:00Z",
        "--image-tag",
        "repo/image:test",
        "--configmap-sha256",
        "abc123",
        "--profile-equivalence",
        "same profile",
        "--stability-off",
        "stable",
        "--stability-on",
        "stable",
        "--crash-loop-off",
        "false",
        "--crash-loop-on",
        "false",
        "--cloudwatch-evidence",
        "cw command",
    ]


@pytest.mark.unit
def test_script_fails_when_flush_latency_metrics_absent(tmp_path: Path) -> None:
    cmd = _base_args(tmp_path) + [
        "--writer-lag-cap-ms",
        "5000",
        "--flush-latency-cap-ms",
        "2000",
        "--report-out",
        str(tmp_path / "report.md"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0
    assert "missing required metric: persist_off_flush_latency_ms" in (
        result.stderr + result.stdout
    )


@pytest.mark.unit
def test_script_fails_when_stability_caps_absent(tmp_path: Path) -> None:
    cmd = _base_args(tmp_path) + [
        "--persist-off-flush-latency-ms",
        "0",
        "--persist-on-flush-latency-ms",
        "100",
        "--report-out",
        str(tmp_path / "report.md"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0
    assert "missing required metric: writer_lag_cap_ms" in (
        result.stderr + result.stdout
    )


@pytest.mark.unit
def test_script_report_contains_dimension_table_and_merge_policy(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "report.md"
    cmd = _base_args(tmp_path) + [
        "--persist-off-flush-latency-ms",
        "0",
        "--persist-on-flush-latency-ms",
        "100",
        "--writer-lag-cap-ms",
        "5000",
        "--flush-latency-cap-ms",
        "2000",
        "--report-out",
        str(report_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    summary = json.loads(result.stdout)
    assert summary["classification"] == "target_pass"
    assert summary["merge_policy_outcome"] == "target-pass"
    content = report_path.read_text(encoding="utf-8")
    assert "## Per-dimension gate table" in content
    assert "## Composite rationale (machine-readable)" in content
    assert "merge policy outcome: `target-pass`" in content
