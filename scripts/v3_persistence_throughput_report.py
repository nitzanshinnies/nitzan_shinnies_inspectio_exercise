#!/usr/bin/env python3
"""Build P12.7 throughput gate report from load-test JSON outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from inspectio.v3.load_harness.stats import (
    HARD_GATE_RATIO_MIN,
    TARGET_GATE_RATIO_MIN,
    classify_throughput_gate,
    throughput_ratio,
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _phase(data: dict[str, Any], idx: int) -> dict[str, Any]:
    phases = data.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ValueError("input JSON missing non-empty 'phases' list")
    return dict(phases[idx])


def _rps_from_phase(phase: dict[str, Any]) -> float:
    value = phase.get("admission_rps")
    if not isinstance(value, (float, int)):
        raise ValueError("phase missing numeric admission_rps")
    return float(value)


def _format_ratio(ratio: float) -> str:
    return f"{round(ratio * 100.0, 2)}%"


def _merge_policy_outcome(gate: str, *, waiver_note: str) -> str:
    if gate == "target_pass":
        return "target-pass"
    if gate == "hard_pass_target_miss":
        return "pass-with-target-miss"
    if waiver_note.strip():
        return "hard-fail-with-waiver"
    return "block"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate P12.7 persistence throughput comparison report",
    )
    parser.add_argument(
        "--persist-off-json",
        required=True,
        help="JSON output file from scripts/v3_load_test.py (persistence-mode=off)",
    )
    parser.add_argument(
        "--persist-on-json",
        required=True,
        help="JSON output file from scripts/v3_load_test.py (persistence-mode=on)",
    )
    parser.add_argument(
        "--phase-index",
        type=int,
        default=-1,
        help="Phase index to compare (default: last)",
    )
    parser.add_argument(
        "--persist-off-delete-rps",
        type=float,
        default=0.0,
        help="Combined send-queue delete throughput (off baseline), from CloudWatch",
    )
    parser.add_argument(
        "--persist-on-delete-rps",
        type=float,
        default=0.0,
        help="Combined send-queue delete throughput (on run), from CloudWatch",
    )
    parser.add_argument(
        "--persist-off-writer-lag-ms",
        type=float,
        default=0.0,
        help="Writer lag metric representative value for off run (usually 0)",
    )
    parser.add_argument(
        "--persist-on-writer-lag-ms",
        type=float,
        default=0.0,
        help="Writer lag metric representative value for on run",
    )
    parser.add_argument(
        "--persist-off-error-rate",
        type=float,
        default=0.0,
        help="Error rate (0..1) for persistence off run",
    )
    parser.add_argument(
        "--persist-on-error-rate",
        type=float,
        default=0.0,
        help="Error rate (0..1) for persistence on run",
    )
    parser.add_argument(
        "--report-out",
        default="plans/v3_phases/P12_7_THROUGHPUT_REPORT.md",
        help="Output markdown report path",
    )
    parser.add_argument(
        "--persist-off-window",
        default="",
        help="CloudWatch window for off run (UTC start..end)",
    )
    parser.add_argument(
        "--persist-on-window",
        default="",
        help="CloudWatch window for on run (UTC start..end)",
    )
    parser.add_argument(
        "--image-tag",
        default="",
        help="Exact benchmark image tag used for both runs",
    )
    parser.add_argument(
        "--configmap-sha256",
        default="",
        help="SHA256 digest of inspectio-v3-config data used for runs",
    )
    parser.add_argument(
        "--profile-equivalence",
        default="",
        help="Short statement proving profile equivalence between off/on runs",
    )
    parser.add_argument(
        "--stability-off",
        default="stable",
        help="Stability statement for off run (e.g. stable/no crash loops)",
    )
    parser.add_argument(
        "--stability-on",
        default="stable",
        help="Stability statement for on run (e.g. stable/no crash loops)",
    )
    parser.add_argument(
        "--waiver-note",
        default="",
        help="Waiver reference if hard gate fails and exception is approved",
    )
    parser.add_argument(
        "--cloudwatch-evidence",
        default="",
        help="CloudWatch query command/reference used for delete throughput + lag",
    )
    args = parser.parse_args()

    off_json = _read_json(Path(args.persist_off_json))
    on_json = _read_json(Path(args.persist_on_json))
    phase_off = _phase(off_json, args.phase_index)
    phase_on = _phase(on_json, args.phase_index)
    off_rps = _rps_from_phase(phase_off)
    on_rps = _rps_from_phase(phase_on)

    ratio = throughput_ratio(on_rps, off_rps)
    gate = classify_throughput_gate(ratio)
    error_rate_delta = round(
        args.persist_on_error_rate - args.persist_off_error_rate, 6
    )
    delete_ratio = throughput_ratio(
        args.persist_on_delete_rps, args.persist_off_delete_rps
    )
    merge_policy = _merge_policy_outcome(gate, waiver_note=args.waiver_note)

    lines = [
        "# P12.7 Throughput Comparison Report",
        "",
        "## Benchmark identity",
        f"- image tag: `{args.image_tag}`",
        f"- configmap sha256: `{args.configmap_sha256}`",
        f"- profile equivalence: `{args.profile_equivalence}`",
        "",
        "## Inputs and artifacts",
        f"- persist-off JSON: `{args.persist_off_json}`",
        f"- persist-on JSON: `{args.persist_on_json}`",
        f"- phase index: `{args.phase_index}`",
        f"- persist-off CloudWatch window: `{args.persist_off_window}`",
        f"- persist-on CloudWatch window: `{args.persist_on_window}`",
        f"- CloudWatch evidence command/reference: `{args.cloudwatch_evidence}`",
        "",
        "## Gate result",
        f"- admission throughput ratio (on/off): `{_format_ratio(ratio)}`",
        f"- hard gate (>= {_format_ratio(HARD_GATE_RATIO_MIN)}): "
        f"`{'PASS' if ratio >= HARD_GATE_RATIO_MIN else 'FAIL'}`",
        f"- target gate (>= {_format_ratio(TARGET_GATE_RATIO_MIN)}): "
        f"`{'PASS' if ratio >= TARGET_GATE_RATIO_MIN else 'MISS'}`",
        f"- classification: `{gate}`",
        f"- merge policy outcome: `{merge_policy}`",
        f"- waiver note: `{args.waiver_note or 'none'}`",
        "",
        "## Required outputs",
        f"- admit throughput off/on: `{off_rps}` / `{on_rps}` recipients/sec",
        f"- combined send-queue delete throughput off/on: "
        f"`{args.persist_off_delete_rps}` / `{args.persist_on_delete_rps}` msgs/sec",
        f"- send delete throughput ratio (on/off): `{_format_ratio(delete_ratio)}`",
        f"- writer lag ms off/on: `{args.persist_off_writer_lag_ms}` / `{args.persist_on_writer_lag_ms}`",
        f"- error rate off/on: `{args.persist_off_error_rate}` / `{args.persist_on_error_rate}`",
        f"- error rate delta (on-off): `{error_rate_delta}`",
        "",
        "## Stability",
        f"- off run stability: `{args.stability_off}`",
        f"- on run stability: `{args.stability_on}`",
        "",
        "## Phase snapshots",
        "```json",
        json.dumps(
            {"persist_off_phase": phase_off, "persist_on_phase": phase_on}, indent=2
        ),
        "```",
        "",
    ]
    out_path = Path(args.report_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps({"ok": True, "gate": gate, "ratio": ratio, "report": str(out_path)})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
