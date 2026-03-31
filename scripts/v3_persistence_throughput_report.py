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
    classify_composite_throughput_gate,
    COMPLETION_HARD_GATE_RATIO_MIN,
    COMPLETION_TARGET_GATE_RATIO_MIN,
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


def _required_number(label: str, value: float | None) -> float:
    if value is None:
        raise ValueError(f"missing required metric: {label}")
    return float(value)


def _required_text(label: str, value: str) -> str:
    if not value.strip():
        raise ValueError(f"missing required text: {label}")
    return value.strip()


def _bool_from_cli(label: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    raise ValueError(f"{label} must be one of true|false|yes|no|1|0")


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
        default=None,
        help="Combined send-queue delete throughput (off baseline), from CloudWatch",
    )
    parser.add_argument(
        "--persist-on-delete-rps",
        type=float,
        default=None,
        help="Combined send-queue delete throughput (on run), from CloudWatch",
    )
    parser.add_argument(
        "--persist-off-writer-lag-ms",
        type=float,
        default=None,
        help="Writer lag metric representative value for off run (usually 0)",
    )
    parser.add_argument(
        "--persist-on-writer-lag-ms",
        type=float,
        default=None,
        help="Writer lag metric representative value for on run",
    )
    parser.add_argument(
        "--persist-off-flush-latency-ms",
        type=float,
        default=None,
        help="Writer flush latency metric representative value for off run",
    )
    parser.add_argument(
        "--persist-on-flush-latency-ms",
        type=float,
        default=None,
        help="Writer flush latency metric representative value for on run",
    )
    parser.add_argument(
        "--writer-lag-cap-ms",
        type=float,
        default=None,
        help="Hard cap for writer lag (ms)",
    )
    parser.add_argument(
        "--flush-latency-cap-ms",
        type=float,
        default=None,
        help="Hard cap for writer flush latency (ms)",
    )
    parser.add_argument(
        "--persist-off-error-rate",
        type=float,
        default=None,
        help="Error rate (0..1) for persistence off run",
    )
    parser.add_argument(
        "--persist-on-error-rate",
        type=float,
        default=None,
        help="Error rate (0..1) for persistence on run",
    )
    parser.add_argument(
        "--report-out",
        default="plans/v3_phases/P12_7_THROUGHPUT_REPORT.md",
        help="Output markdown report path",
    )
    parser.add_argument(
        "--persist-off-window",
        required=True,
        help="CloudWatch window for off run (UTC start..end)",
    )
    parser.add_argument(
        "--persist-on-window",
        required=True,
        help="CloudWatch window for on run (UTC start..end)",
    )
    parser.add_argument(
        "--image-tag",
        required=True,
        help="Exact benchmark image tag used for both runs",
    )
    parser.add_argument(
        "--configmap-sha256",
        required=True,
        help="SHA256 digest of inspectio-v3-config data used for runs",
    )
    parser.add_argument(
        "--profile-equivalence",
        required=True,
        help="Short statement proving profile equivalence between off/on runs",
    )
    parser.add_argument(
        "--stability-off",
        required=True,
        help="Stability statement for off run (e.g. stable/no crash loops)",
    )
    parser.add_argument(
        "--stability-on",
        required=True,
        help="Stability statement for on run (e.g. stable/no crash loops)",
    )
    parser.add_argument(
        "--crash-loop-off",
        required=True,
        help="Crash-loop observed in off run (true|false)",
    )
    parser.add_argument(
        "--crash-loop-on",
        required=True,
        help="Crash-loop observed in on run (true|false)",
    )
    parser.add_argument(
        "--waiver-note",
        default="",
        help="Waiver reference if hard gate fails and exception is approved",
    )
    parser.add_argument(
        "--cloudwatch-evidence",
        required=True,
        help="CloudWatch query command/reference used for delete throughput + lag",
    )
    args = parser.parse_args()

    off_json = _read_json(Path(args.persist_off_json))
    on_json = _read_json(Path(args.persist_on_json))
    phase_off = _phase(off_json, args.phase_index)
    phase_on = _phase(on_json, args.phase_index)
    off_rps = _rps_from_phase(phase_off)
    on_rps = _rps_from_phase(phase_on)

    persist_off_delete_rps = _required_number(
        "persist_off_delete_rps", args.persist_off_delete_rps
    )
    persist_on_delete_rps = _required_number(
        "persist_on_delete_rps", args.persist_on_delete_rps
    )
    persist_off_writer_lag_ms = _required_number(
        "persist_off_writer_lag_ms", args.persist_off_writer_lag_ms
    )
    persist_on_writer_lag_ms = _required_number(
        "persist_on_writer_lag_ms", args.persist_on_writer_lag_ms
    )
    persist_off_flush_latency_ms = _required_number(
        "persist_off_flush_latency_ms", args.persist_off_flush_latency_ms
    )
    persist_on_flush_latency_ms = _required_number(
        "persist_on_flush_latency_ms", args.persist_on_flush_latency_ms
    )
    writer_lag_cap_ms = _required_number("writer_lag_cap_ms", args.writer_lag_cap_ms)
    flush_latency_cap_ms = _required_number(
        "flush_latency_cap_ms", args.flush_latency_cap_ms
    )
    persist_off_error_rate = _required_number(
        "persist_off_error_rate", args.persist_off_error_rate
    )
    persist_on_error_rate = _required_number(
        "persist_on_error_rate", args.persist_on_error_rate
    )
    persist_off_window = _required_text("persist_off_window", args.persist_off_window)
    persist_on_window = _required_text("persist_on_window", args.persist_on_window)
    image_tag = _required_text("image_tag", args.image_tag)
    configmap_sha = _required_text("configmap_sha256", args.configmap_sha256)
    profile_equivalence = _required_text(
        "profile_equivalence", args.profile_equivalence
    )
    stability_off = _required_text("stability_off", args.stability_off)
    stability_on = _required_text("stability_on", args.stability_on)
    cloudwatch_evidence = _required_text(
        "cloudwatch_evidence", args.cloudwatch_evidence
    )
    crash_loop_off = _bool_from_cli("crash_loop_off", args.crash_loop_off)
    crash_loop_on = _bool_from_cli("crash_loop_on", args.crash_loop_on)

    admission_ratio = throughput_ratio(on_rps, off_rps)
    completion_ratio = throughput_ratio(persist_on_delete_rps, persist_off_delete_rps)
    composite = classify_composite_throughput_gate(
        admission_ratio=admission_ratio,
        completion_ratio=completion_ratio,
        writer_lag_on_ms=persist_on_writer_lag_ms,
        writer_lag_cap_ms=writer_lag_cap_ms,
        flush_latency_on_ms=persist_on_flush_latency_ms,
        flush_latency_cap_ms=flush_latency_cap_ms,
        crash_loop_off=crash_loop_off,
        crash_loop_on=crash_loop_on,
    )
    gate = str(composite["classification"])
    error_rate_delta = round(persist_on_error_rate - persist_off_error_rate, 6)
    merge_policy = _merge_policy_outcome(gate, waiver_note=args.waiver_note)

    lines = [
        "# P12.7 Throughput Comparison Report",
        "",
        "## Benchmark identity",
        f"- image tag: `{image_tag}`",
        f"- configmap sha256: `{configmap_sha}`",
        f"- profile equivalence: `{profile_equivalence}`",
        "",
        "## Inputs and artifacts",
        f"- persist-off JSON: `{args.persist_off_json}`",
        f"- persist-on JSON: `{args.persist_on_json}`",
        f"- phase index: `{args.phase_index}`",
        f"- persist-off CloudWatch window: `{persist_off_window}`",
        f"- persist-on CloudWatch window: `{persist_on_window}`",
        f"- CloudWatch evidence command/reference: `{cloudwatch_evidence}`",
        "",
        "## Gate result",
        f"- admission throughput ratio (on/off): `{_format_ratio(admission_ratio)}`",
        f"- hard gate (>= {_format_ratio(HARD_GATE_RATIO_MIN)}): "
        f"`{'PASS' if bool(composite['admission_hard_pass']) else 'FAIL'}`",
        f"- target gate (>= {_format_ratio(TARGET_GATE_RATIO_MIN)}): "
        f"`{'PASS' if bool(composite['admission_target_pass']) else 'MISS'}`",
        f"- completion hard gate (>= {_format_ratio(COMPLETION_HARD_GATE_RATIO_MIN)}): "
        f"`{'PASS' if bool(composite['completion_hard_pass']) else 'FAIL'}`",
        f"- completion target gate (>= {_format_ratio(COMPLETION_TARGET_GATE_RATIO_MIN)}): "
        f"`{'PASS' if bool(composite['completion_target_pass']) else 'MISS'}`",
        f"- classification: `{gate}`",
        f"- merge policy outcome: `{merge_policy}`",
        f"- waiver note: `{args.waiver_note or 'none'}`",
        "",
        "## Required outputs",
        f"- admit throughput off/on: `{off_rps}` / `{on_rps}` recipients/sec",
        f"- combined send-queue delete throughput off/on: "
        f"`{persist_off_delete_rps}` / `{persist_on_delete_rps}` msgs/sec",
        f"- send delete throughput ratio (on/off): `{_format_ratio(completion_ratio)}`",
        f"- writer lag ms off/on: `{persist_off_writer_lag_ms}` / `{persist_on_writer_lag_ms}`",
        f"- writer flush latency ms off/on: `{persist_off_flush_latency_ms}` / `{persist_on_flush_latency_ms}`",
        f"- writer lag cap ms: `{writer_lag_cap_ms}`",
        f"- flush latency cap ms: `{flush_latency_cap_ms}`",
        f"- error rate off/on: `{persist_off_error_rate}` / `{persist_on_error_rate}`",
        f"- error rate delta (on-off): `{error_rate_delta}`",
        "",
        "## Per-dimension gate table",
        "| Dimension | Hard Pass | Target Pass |",
        "|---|---|---|",
        f"| Admission ratio | `{bool(composite['admission_hard_pass'])}` | `{bool(composite['admission_target_pass'])}` |",
        f"| Completion ratio | `{bool(composite['completion_hard_pass'])}` | `{bool(composite['completion_target_pass'])}` |",
        "",
        "## Stability",
        f"- off run stability: `{stability_off}`",
        f"- on run stability: `{stability_on}`",
        f"- crash-loop check off/on (must be false): `{crash_loop_off}` / `{crash_loop_on}`",
        f"- crash-loop pass: `{bool(composite['crash_loop_pass'])}`",
        f"- writer lag cap pass: `{bool(composite['writer_lag_cap_pass'])}`",
        f"- flush latency cap pass: `{bool(composite['flush_latency_cap_pass'])}`",
        "",
        "## Phase snapshots",
        "```json",
        json.dumps(
            {"persist_off_phase": phase_off, "persist_on_phase": phase_on}, indent=2
        ),
        "```",
        "",
        "## Composite rationale (machine-readable)",
        "```json",
        json.dumps(composite, indent=2),
        "```",
        "",
    ]
    out_path = Path(args.report_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "classification": gate,
                "merge_policy_outcome": merge_policy,
                "admission_ratio": admission_ratio,
                "completion_ratio": completion_ratio,
                "rationale": composite,
                "report": str(out_path),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
