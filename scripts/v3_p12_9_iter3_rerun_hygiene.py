"""P12.9 WS3.1: Iteration-3 rerun measurement hygiene validator."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3

DEFAULT_PERIOD_SEC = 60
DEFAULT_PRELOAD_SEC = 60
DEFAULT_TAIL_SEC = 120
MIN_ACTIVE_PERIODS = 5
PROMOTION_THRESHOLD_PERCENT = 52.66
MAX_DATAPOINT_DIFF = 1
SEND_QUEUE_NAMES = [f"inspectio-v3-send-{index}" for index in range(8)]
SUMMARY_PATTERN = re.compile(
    r"admitted_total=(\d+) duration_sec=([0-9.]+) offered_admit_rps=([0-9.]+) "
    r"concurrency=(\d+) batch=(\d+)(?: transient_errors=(\d+))?"
)


@dataclass(frozen=True, slots=True)
class ProfileWindow:
    start_utc: datetime
    end_utc: datetime
    query_start_utc: datetime
    query_end_utc: datetime


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--art-dir", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--cluster-context", required=True)
    parser.add_argument("--namespace", default="inspectio")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--period-sec", type=int, default=DEFAULT_PERIOD_SEC)
    parser.add_argument("--preload-sec", type=int, default=DEFAULT_PRELOAD_SEC)
    parser.add_argument("--tail-sec", type=int, default=DEFAULT_TAIL_SEC)
    parser.add_argument("--stat", default="Sum")
    parser.add_argument(
        "--on-start-utc",
        default=None,
        help="Override persist-on window start (ISO-8601 Z). Use with --on-end-utc if on_start.txt/on_end.txt absent or wrong.",
    )
    parser.add_argument(
        "--on-end-utc",
        default=None,
        help="Override persist-on window end (ISO-8601 Z). Required with --on-start-utc when on_end.txt is missing.",
    )
    parser.add_argument(
        "--allow-missing-on-sustain",
        action="store_true",
        help="If on-allpods.log has no SUSTAIN_SUMMARY, write sustain_summaries.on as an error object instead of failing.",
    )
    parser.add_argument(
        "--emit-metrics-exit-zero",
        action="store_true",
        help="Write JSON outputs then exit 0 even when measurement_valid is false (still prints cw_metrics to stdout).",
    )
    return parser.parse_args()


def _read_timestamp(path: Path) -> datetime:
    text = path.read_text().strip()
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _load_profile_window(
    *,
    start_path: Path,
    end_path: Path,
    preload_sec: int,
    tail_sec: int,
) -> ProfileWindow:
    start_utc = _read_timestamp(start_path)
    end_utc = _read_timestamp(end_path)
    return _profile_window_from_times(
        start_utc=start_utc,
        end_utc=end_utc,
        preload_sec=preload_sec,
        tail_sec=tail_sec,
    )


def _parse_iso_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _profile_window_from_times(
    *,
    start_utc: datetime,
    end_utc: datetime,
    preload_sec: int,
    tail_sec: int,
) -> ProfileWindow:
    return ProfileWindow(
        start_utc=start_utc,
        end_utc=end_utc,
        query_start_utc=start_utc - timedelta(seconds=preload_sec),
        query_end_utc=end_utc + timedelta(seconds=tail_sec),
    )


def _parse_sustain_summary(log_path: Path) -> dict[str, Any]:
    lines = [
        line for line in log_path.read_text().splitlines() if "SUSTAIN_SUMMARY" in line
    ]
    if not lines:
        raise ValueError(f"no SUSTAIN_SUMMARY line in {log_path}")
    line = lines[-1]
    matched = SUMMARY_PATTERN.search(line)
    if matched is None:
        raise ValueError(f"failed to parse summary line in {log_path}")
    out: dict[str, Any] = {
        "admitted_total": int(matched.group(1)),
        "duration_sec": float(matched.group(2)),
        "offered_admit_rps": float(matched.group(3)),
        "concurrency": int(matched.group(4)),
        "batch": int(matched.group(5)),
        "raw_line": line,
    }
    if matched.group(6) is not None:
        out["transient_errors"] = int(matched.group(6))
    return out


def _load_job_status(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    status = payload.get("status", {})
    succeeded = int(status.get("succeeded", 0))
    failed = int(status.get("failed", 0))
    valid = succeeded == 1 and failed == 0
    return {
        "succeeded": succeeded,
        "failed": failed,
        "valid_single_attempt": valid,
    }


def _query_completion_series(
    *,
    cloudwatch: Any,
    window: ProfileWindow,
    period_sec: int,
    stat: str,
) -> list[float]:
    queries: list[dict[str, Any]] = []
    for queue_index, queue_name in enumerate(SEND_QUEUE_NAMES):
        queries.append(
            {
                "Id": f"q{queue_index}",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/SQS",
                        "MetricName": "NumberOfMessagesDeleted",
                        "Dimensions": [{"Name": "QueueName", "Value": queue_name}],
                    },
                    "Period": period_sec,
                    "Stat": stat,
                },
                "ReturnData": True,
            }
        )
    response = cloudwatch.get_metric_data(
        MetricDataQueries=queries,
        StartTime=window.query_start_utc,
        EndTime=window.query_end_utc,
        ScanBy="TimestampAscending",
    )
    summed_by_timestamp: dict[datetime, float] = {}
    for item in response.get("MetricDataResults", []):
        for timestamp, value in zip(
            item.get("Timestamps", []),
            item.get("Values", []),
            strict=False,
        ):
            summed_by_timestamp[timestamp] = summed_by_timestamp.get(
                timestamp, 0.0
            ) + float(value)
    points_rps = [
        summed_value / period_sec
        for _, summed_value in sorted(
            summed_by_timestamp.items(), key=lambda entry: entry[0]
        )
    ]
    return points_rps


def _series_metrics(
    *,
    points_rps: list[float],
    window: ProfileWindow,
    period_sec: int,
) -> dict[str, Any]:
    combined_avg_rps = sum(points_rps) / len(points_rps) if points_rps else 0.0
    combined_peak_rps = max(points_rps) if points_rps else 0.0
    active_periods = sum(1 for value in points_rps if value > 0.0)
    return {
        "window_start_utc": window.start_utc.isoformat().replace("+00:00", "Z"),
        "window_end_utc": window.end_utc.isoformat().replace("+00:00", "Z"),
        "query_start_utc": window.query_start_utc.isoformat().replace("+00:00", "Z"),
        "query_end_utc": window.query_end_utc.isoformat().replace("+00:00", "Z"),
        "period_sec": period_sec,
        "datapoints": len(points_rps),
        "active_periods": active_periods,
        "combined_avg_rps": combined_avg_rps,
        "combined_peak_rps": combined_peak_rps,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main() -> None:
    args = _parse_args()
    art_dir = Path(args.art_dir)
    art_dir.mkdir(parents=True, exist_ok=True)
    off_window = _load_profile_window(
        start_path=art_dir / "off_start.txt",
        end_path=art_dir / "off_end.txt",
        preload_sec=args.preload_sec,
        tail_sec=args.tail_sec,
    )
    on_end_path = art_dir / "on_end.txt"
    if args.on_start_utc and args.on_end_utc:
        on_window = _profile_window_from_times(
            start_utc=_parse_iso_utc(args.on_start_utc),
            end_utc=_parse_iso_utc(args.on_end_utc),
            preload_sec=args.preload_sec,
            tail_sec=args.tail_sec,
        )
    elif on_end_path.exists():
        on_window = _load_profile_window(
            start_path=art_dir / "on_start.txt",
            end_path=on_end_path,
            preload_sec=args.preload_sec,
            tail_sec=args.tail_sec,
        )
    else:
        raise SystemExit(
            "Missing on_end.txt. Provide --on-start-utc and --on-end-utc (ISO-8601 Z) "
            "to define the persist-on CloudWatch window."
        )

    try:
        on_sustain = _parse_sustain_summary(art_dir / "on-allpods.log")
    except ValueError as exc:
        if args.allow_missing_on_sustain:
            on_sustain = {"parse_error": str(exc)}
        else:
            raise
    sustain_summaries = {
        "off": _parse_sustain_summary(art_dir / "off-allpods.log"),
        "on": on_sustain,
    }
    _write_json(art_dir / "sustain_summaries.json", sustain_summaries)

    job_validity = {
        "off": _load_job_status(art_dir / "off_job_status.json"),
        "on": _load_job_status(art_dir / "on_job_status.json"),
    }

    cloudwatch = boto3.client("cloudwatch", region_name=args.region)
    off_series = _query_completion_series(
        cloudwatch=cloudwatch,
        window=off_window,
        period_sec=args.period_sec,
        stat=args.stat,
    )
    on_series = _query_completion_series(
        cloudwatch=cloudwatch,
        window=on_window,
        period_sec=args.period_sec,
        stat=args.stat,
    )
    off_metrics = _series_metrics(
        points_rps=off_series, window=off_window, period_sec=args.period_sec
    )
    on_metrics = _series_metrics(
        points_rps=on_series, window=on_window, period_sec=args.period_sec
    )
    ratio_percent = (
        (on_metrics["combined_avg_rps"] / off_metrics["combined_avg_rps"]) * 100.0
        if off_metrics["combined_avg_rps"] > 0
        else 0.0
    )
    datapoint_diff = abs(off_metrics["datapoints"] - on_metrics["datapoints"])
    validity_checks = {
        "off_single_success_zero_failed": job_validity["off"]["valid_single_attempt"],
        "on_single_success_zero_failed": job_validity["on"]["valid_single_attempt"],
        "off_active_periods_gte_5": off_metrics["active_periods"] >= MIN_ACTIVE_PERIODS,
        "on_active_periods_gte_5": on_metrics["active_periods"] >= MIN_ACTIVE_PERIODS,
        "datapoint_count_diff_lte_1": datapoint_diff <= MAX_DATAPOINT_DIFF,
        "period_is_60s": args.period_sec == DEFAULT_PERIOD_SEC,
        "stat_is_sum": args.stat == "Sum",
    }
    measurement_valid = all(validity_checks.values())
    decision = "PROMOTE" if ratio_percent >= PROMOTION_THRESHOLD_PERCENT else "NO-GO"

    cw_metrics = {
        "metric": "AWS/SQS NumberOfMessagesDeleted",
        "queues": SEND_QUEUE_NAMES,
        "off": off_metrics,
        "on": on_metrics,
        "completion_ratio_percent_on_over_off": ratio_percent,
        "datapoint_count_difference": datapoint_diff,
        "validity_checks": validity_checks,
        "measurement_valid": measurement_valid,
        "decision_threshold_percent": PROMOTION_THRESHOLD_PERCENT,
        "decision": decision,
        "job_validity": job_validity,
    }
    _write_json(art_dir / "cw_metrics.json", cw_metrics)

    manifest = {
        "profile": "iter-3-rerun",
        "cluster_context": args.cluster_context,
        "namespace": args.namespace,
        "image_under_test": args.image,
        "benchmark_shape": {"duration_sec": 240, "concurrency": 120, "batch": 200},
        "on_window_source": (
            "cli_utc_override"
            if args.on_start_utc and args.on_end_utc
            else "artifact_on_start_txt_and_on_end_txt"
        ),
        "query_policy": {
            "metric": "AWS/SQS NumberOfMessagesDeleted",
            "period_sec": args.period_sec,
            "stat": args.stat,
            "preload_sec": args.preload_sec,
            "tail_sec": args.tail_sec,
        },
        "windows": {"off": off_metrics, "on": on_metrics},
        "job_validity": job_validity,
        "measurement_valid": measurement_valid,
    }
    _write_json(art_dir / "measurement_manifest.json", manifest)

    print(json.dumps(cw_metrics, indent=2, sort_keys=True))
    if not measurement_valid and not args.emit_metrics_exit_zero:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
