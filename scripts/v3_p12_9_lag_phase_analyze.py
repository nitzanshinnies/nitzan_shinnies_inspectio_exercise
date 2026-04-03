#!/usr/bin/env python3
"""P12.9 Phase 1: analyze benchmark artifacts locally (no AWS).

Parses sustain summaries, job status, and scans load logs for common failure modes.
See plans/v3_phases/P12_9_LAG_LOCALIZATION_PLAN.md.

Exit codes: 0 = ready for Phase 2 (hygiene); 1 = invalid/incomplete run (fix jobs or
timestamps); 2 = missing Phase-1 inputs or ``--strict`` file gaps.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SUMMARY_LINE = re.compile(
    r"admitted_total=(\d+) duration_sec=([0-9.]+) offered_admit_rps=([0-9.]+) "
    r"concurrency=(\d+) batch=(\d+)(?: transient_errors=(\d+))?"
)

LOG_MARKERS = (
    ("http_5xx_or_status", re.compile(r"\b5\d{2}\b|HTTPStatusError|status_code=5")),
    ("httpx_read_error", re.compile(r"ReadError|httpcore\.ReadError", re.I)),
    ("client_closed", re.compile(r"client has been closed", re.I)),
    ("traceback", re.compile(r"Traceback \(most recent call last\)")),
    ("backoff_limit", re.compile(r"BackoffLimitExceeded|backoff limit", re.I)),
    (
        "persist_backpressure",
        re.compile(r"PersistenceTransportBackpressure|inflight cap", re.I),
    ),
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--art-dir",
        type=Path,
        required=True,
        help="Artifact directory (e.g. plans/v3_phases/artifacts/p12_9/iter-6)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Require all files for CloudWatch/hygiene (off/on *_end.txt); exit non-zero if any missing.",
    )
    return p.parse_args()


def _parse_sustain_summary(log_path: Path) -> dict[str, Any]:
    lines = [ln for ln in log_path.read_text().splitlines() if "SUSTAIN_SUMMARY" in ln]
    if not lines:
        return {"error": f"no SUSTAIN_SUMMARY in {log_path}"}
    line = lines[-1]
    m = SUMMARY_LINE.search(line)
    if m is None:
        return {
            "error": f"unparseable SUSTAIN_SUMMARY in {log_path}",
            "raw_tail": line[-200:],
        }
    out: dict[str, Any] = {
        "admitted_total": int(m.group(1)),
        "duration_sec": float(m.group(2)),
        "offered_admit_rps": float(m.group(3)),
        "concurrency": int(m.group(4)),
        "batch": int(m.group(5)),
    }
    if m.group(6) is not None:
        out["transient_errors"] = int(m.group(6))
    return out


def _job_valid(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    st = payload.get("status", {})
    succeeded = int(st.get("succeeded", 0))
    failed = int(st.get("failed", 0))
    return {
        "succeeded": succeeded,
        "failed": failed,
        "valid_single_attempt": succeeded == 1 and failed == 0,
    }


def _scan_log(path: Path) -> dict[str, int]:
    text = path.read_text(errors="replace")
    return {name: len(rx.findall(text)) for name, rx in LOG_MARKERS}


def main() -> int:
    args = _parse_args()
    art: Path = args.art_dir.resolve()
    if not art.is_dir():
        print(json.dumps({"error": f"not a directory: {art}"}, indent=2))
        return 2

    required_phase1 = [
        "off-allpods.log",
        "off_job_status.json",
        "on-allpods.log",
        "on_job_status.json",
    ]
    required_windows = [
        "off_start.txt",
        "off_end.txt",
        "on_start.txt",
        "on_end.txt",
    ]
    missing_phase1 = [p for p in required_phase1 if not (art / p).exists()]
    missing_windows = [p for p in required_windows if not (art / p).exists()]
    missing_strict = missing_phase1 + missing_windows

    off_summary = _parse_sustain_summary(art / "off-allpods.log")
    on_summary = _parse_sustain_summary(art / "on-allpods.log")
    off_job = (
        _job_valid(art / "off_job_status.json")
        if (art / "off_job_status.json").exists()
        else {}
    )
    on_job = (
        _job_valid(art / "on_job_status.json")
        if (art / "on_job_status.json").exists()
        else {}
    )

    report: dict[str, Any] = {
        "art_dir": str(art),
        "missing_phase1_files": missing_phase1,
        "missing_window_timestamps_for_cloudwatch": missing_windows,
        "strict_mode": args.strict,
        "off_sustain": off_summary,
        "on_sustain": on_summary,
        "off_job": off_job,
        "on_job": on_job,
        "off_log_markers": _scan_log(art / "off-allpods.log")
        if (art / "off-allpods.log").exists()
        else {},
        "on_log_markers": _scan_log(art / "on-allpods.log")
        if (art / "on-allpods.log").exists()
        else {},
    }

    if (
        "error" not in off_summary
        and "error" not in on_summary
        and "offered_admit_rps" in off_summary
        and "offered_admit_rps" in on_summary
    ):
        off_rps = float(off_summary["offered_admit_rps"])
        on_rps = float(on_summary["offered_admit_rps"])
        report["admit_rps_ratio_on_over_off"] = (
            round((on_rps / off_rps) * 100.0, 3) if off_rps > 0 else None
        )

    phase1_ok = not missing_phase1
    jobs_valid = bool(
        off_job.get("valid_single_attempt") and on_job.get("valid_single_attempt"),
    )
    windows_ok = not missing_windows
    report["phase1_gate"] = {
        "phase1_inputs_complete": phase1_ok,
        "jobs_valid": jobs_valid,
        "timestamp_files_ready_for_cloudwatch": windows_ok,
        "next_step": _next_step(phase1_ok, jobs_valid, windows_ok),
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.strict and missing_strict:
        return 2
    if missing_phase1:
        return 2
    if not jobs_valid:
        return 1
    if not windows_ok:
        return 1
    return 0


def _next_step(phase1_ok: bool, jobs_valid: bool, windows_ok: bool) -> str:
    if not phase1_ok:
        return "Add missing off/on logs and job status JSON, then re-run this script."
    if not jobs_valid:
        return "Fix failed/invalid load jobs (check on_log_markers); do not run hygiene or interpret completion ratio."
    if not windows_ok:
        return (
            "Jobs valid but timestamp files missing — add on_end.txt (and any missing *start/end*) "
            "before Phase 2 (hygiene.py)."
        )
    return "Run Phase 2: scripts/v3_p12_9_iter3_rerun_hygiene.py with AWS credentials to produce cw_metrics.json."


if __name__ == "__main__":
    sys.exit(main())
