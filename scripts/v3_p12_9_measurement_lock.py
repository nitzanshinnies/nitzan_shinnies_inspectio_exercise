#!/usr/bin/env python3
"""Build P12.9 WS1 measurement integrity artifacts from benchmark runs."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3


WINDOW_PRELOAD_SECONDS = 60
WINDOW_TAIL_SECONDS = 120
CW_PERIOD_SECONDS = 60
CW_STAT_SUM = "Sum"
CW_STAT_MAX = "Maximum"


@dataclass(frozen=True)
class RunWindow:
    profile: str
    run_id: str
    start_utc: datetime
    end_utc: datetime


@dataclass(frozen=True)
class QueryWindow:
    profile: str
    run_id: str
    job_start_utc: datetime
    job_end_utc: datetime
    query_start_utc: datetime
    query_end_utc: datetime


def _parse_utc(ts: str) -> datetime:
    return datetime.strptime(ts.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _read_run_window(*, runs_dir: Path, profile: str, run_id: str) -> RunWindow:
    start = _parse_utc((runs_dir / f"{run_id}_{profile}_start.txt").read_text("utf-8"))
    end = _parse_utc((runs_dir / f"{run_id}_{profile}_end.txt").read_text("utf-8"))
    return RunWindow(profile=profile, run_id=run_id, start_utc=start, end_utc=end)


def _build_query_windows(
    *,
    run_windows: list[RunWindow],
    preload_seconds: int,
    tail_seconds: int,
) -> list[QueryWindow]:
    return [
        QueryWindow(
            profile=run.profile,
            run_id=run.run_id,
            job_start_utc=run.start_utc,
            job_end_utc=run.end_utc,
            query_start_utc=run.start_utc - timedelta(seconds=preload_seconds),
            query_end_utc=run.end_utc + timedelta(seconds=tail_seconds),
        )
        for run in run_windows
    ]


def _find_query_window_overlaps(
    query_windows: list[QueryWindow],
) -> list[tuple[str, str]]:
    sorted_windows = sorted(query_windows, key=lambda window: window.query_start_utc)
    overlaps: list[tuple[str, str]] = []
    for current, nxt in zip(sorted_windows, sorted_windows[1:], strict=False):
        if nxt.query_start_utc < current.query_end_utc:
            overlaps.append(
                (
                    f"{current.run_id}-{current.profile}",
                    f"{nxt.run_id}-{nxt.profile}",
                )
            )
    return overlaps


def _sum_series(
    cw: Any,
    *,
    queue_name: str,
    metric_name: str,
    stat: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    resp = cw.get_metric_statistics(
        Namespace="AWS/SQS",
        MetricName=metric_name,
        Dimensions=[{"Name": "QueueName", "Value": queue_name}],
        StartTime=start,
        EndTime=end,
        Period=CW_PERIOD_SECONDS,
        Statistics=[stat],
    )
    dps = sorted(resp.get("Datapoints", []), key=lambda dp: dp["Timestamp"])
    out: list[dict[str, Any]] = []
    key = stat.lower()
    for dp in dps:
        out.append(
            {
                "timestamp": dp["Timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                key: float(dp[stat]),
            }
        )
    return out


def _profile_metrics(
    cw: Any,
    *,
    run: QueryWindow,
    send_queues: list[str],
    persist_queues: list[str],
) -> dict[str, Any]:
    send_delete_by_queue: dict[str, Any] = {}
    delete_total = 0.0
    for queue_name in send_queues:
        rows = _sum_series(
            cw,
            queue_name=queue_name,
            metric_name="NumberOfMessagesDeleted",
            stat=CW_STAT_SUM,
            start=run.query_start_utc,
            end=run.query_end_utc,
        )
        queue_sum = sum(row["sum"] for row in rows)
        delete_total += queue_sum
        send_delete_by_queue[queue_name] = {"sum": queue_sum, "datapoints": rows}

    persist_lag_by_queue: dict[str, Any] = {}
    lag_max_seconds = 0.0
    for queue_name in persist_queues:
        rows = _sum_series(
            cw,
            queue_name=queue_name,
            metric_name="ApproximateAgeOfOldestMessage",
            stat=CW_STAT_MAX,
            start=run.query_start_utc,
            end=run.query_end_utc,
        )
        queue_max = max((row["maximum"] for row in rows), default=0.0)
        lag_max_seconds = max(lag_max_seconds, queue_max)
        persist_lag_by_queue[queue_name] = {
            "max_seconds": queue_max,
            "datapoints": rows,
        }

    combined_by_timestamp: dict[str, float] = {}
    for queue_data in send_delete_by_queue.values():
        for row in queue_data["datapoints"]:
            ts = str(row["timestamp"])
            combined_by_timestamp[ts] = combined_by_timestamp.get(ts, 0.0) + float(
                row["sum"]
            )

    window_seconds = (run.query_end_utc - run.query_start_utc).total_seconds()
    peak_minute_sum = max(combined_by_timestamp.values(), default=0.0)
    return {
        "profile": run.profile,
        "run_id": run.run_id,
        "job_window_utc": f"{run.job_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}..{run.job_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "query_window_utc": f"{run.query_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}..{run.query_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "query_window_seconds": window_seconds,
        "delete_total": delete_total,
        "combined_avg_rps": (
            delete_total / window_seconds if window_seconds > 0 else 0.0
        ),
        "combined_peak_rps": peak_minute_sum / CW_PERIOD_SECONDS,
        "combined_by_timestamp": combined_by_timestamp,
        "persist_lag_max_seconds": lag_max_seconds,
        "send_delete_by_queue": send_delete_by_queue,
        "persist_lag_by_queue": persist_lag_by_queue,
    }


def _variance_percent(a: float, b: float) -> float:
    denom = max(1e-9, (a + b) / 2.0)
    return abs(a - b) / denom * 100.0


def _profile_gate_summary(
    *,
    runs: list[dict[str, Any]],
    profile: str,
    gate_metric: str,
    threshold_percent: float,
) -> dict[str, Any]:
    profile_runs = [run for run in runs if str(run["profile"]) == profile]
    if len(profile_runs) != 2:
        raise ValueError(
            f"expected exactly 2 runs for profile {profile}, got {len(profile_runs)}"
        )
    values = [float(run[gate_metric]) for run in profile_runs]
    variance = _variance_percent(values[0], values[1])
    return {
        "values": values,
        "variance_percent": round(variance, 3),
        "threshold_percent": threshold_percent,
        "pass": variance <= threshold_percent,
    }


def _active_period_count(run: dict[str, Any]) -> int:
    active = 0
    for value in dict(run["combined_by_timestamp"]).values():
        if float(value) > 0:
            active += 1
    return active


def _validate_gate_metric(*, repro_metric: str, allow_peak_gate: bool) -> None:
    if repro_metric == "combined_peak_rps" and not allow_peak_gate:
        raise ValueError(
            "combined_peak_rps cannot be used as sole gate metric without --allow-peak-gate"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate P12.9 measurement lock artifacts"
    )
    parser.add_argument(
        "--runs-dir",
        default="plans/v3_phases/artifacts/p12_9/runs",
        help="Directory containing r1/r2 *_start.txt and *_end.txt files",
    )
    parser.add_argument(
        "--output-dir",
        default="plans/v3_phases/artifacts/p12_9",
        help="Artifact output directory",
    )
    parser.add_argument(
        "--send-shard-count",
        type=int,
        default=8,
        help="Number of active send shards",
    )
    parser.add_argument(
        "--persist-shard-count",
        type=int,
        default=8,
        help="Number of active persistence shards",
    )
    parser.add_argument(
        "--variance-threshold-percent",
        type=float,
        default=10.0,
        help="Reproducibility variance threshold per profile",
    )
    parser.add_argument(
        "--window-preload-seconds",
        type=int,
        default=WINDOW_PRELOAD_SECONDS,
        help="Seconds before job start to include in query window",
    )
    parser.add_argument(
        "--window-tail-seconds",
        type=int,
        default=WINDOW_TAIL_SECONDS,
        help="Seconds after job end to include in query window",
    )
    parser.add_argument(
        "--repro-metric",
        choices=("combined_avg_rps", "normalized_delete_rps", "combined_peak_rps"),
        default="combined_avg_rps",
        help="Metric used for WS1 reproducibility gate",
    )
    parser.add_argument(
        "--allow-peak-gate",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Allow combined_peak_rps as gate metric (requires explicit opt-in)",
    )
    parser.add_argument(
        "--min-active-periods",
        type=int,
        default=3,
        help="Minimum non-zero CW periods required per run",
    )
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    send_queues = [f"inspectio-v3-send-{i}" for i in range(args.send_shard_count)]
    persist_queues = [
        f"inspectio-v3-persist-transport-{i}" for i in range(args.persist_shard_count)
    ]

    run_windows_raw = [
        _read_run_window(runs_dir=runs_dir, profile="off", run_id="r1"),
        _read_run_window(runs_dir=runs_dir, profile="on", run_id="r1"),
        _read_run_window(runs_dir=runs_dir, profile="off", run_id="r2"),
        _read_run_window(runs_dir=runs_dir, profile="on", run_id="r2"),
    ]
    run_windows = _build_query_windows(
        run_windows=run_windows_raw,
        preload_seconds=args.window_preload_seconds,
        tail_seconds=args.window_tail_seconds,
    )
    overlaps = _find_query_window_overlaps(run_windows)
    if overlaps:
        raise SystemExit(
            "overlapping query windows detected: "
            + ", ".join([f"{left}<->{right}" for left, right in overlaps])
        )
    try:
        _validate_gate_metric(
            repro_metric=args.repro_metric, allow_peak_gate=args.allow_peak_gate
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    cw = boto3.client("cloudwatch", region_name="us-east-1")
    metrics = [
        _profile_metrics(
            cw,
            run=run,
            send_queues=send_queues,
            persist_queues=persist_queues,
        )
        for run in run_windows
    ]
    for run in metrics:
        run["normalized_delete_rps"] = float(run["delete_total"]) / max(
            1e-9, float(run["query_window_seconds"])
        )
        run["active_period_count"] = _active_period_count(run)
        if int(run["active_period_count"]) < args.min_active_periods:
            raise SystemExit(
                f"insufficient completion activity periods for {run['run_id']}-{run['profile']}: "
                f"{run['active_period_count']} < {args.min_active_periods}"
            )

    off_gate = _profile_gate_summary(
        runs=metrics,
        profile="off",
        gate_metric=args.repro_metric,
        threshold_percent=args.variance_threshold_percent,
    )
    on_gate = _profile_gate_summary(
        runs=metrics,
        profile="on",
        gate_metric=args.repro_metric,
        threshold_percent=args.variance_threshold_percent,
    )
    reproducible = bool(off_gate["pass"]) and bool(on_gate["pass"])

    manifest = {
        "namespace": "AWS/SQS",
        "measurement_method": "sum NumberOfMessagesDeleted across send shards",
        "lag_method": "max ApproximateAgeOfOldestMessage across persistence shards",
        "send_metric": {
            "name": "NumberOfMessagesDeleted",
            "stat": CW_STAT_SUM,
            "period_seconds": CW_PERIOD_SECONDS,
            "dimensions": [{"QueueName": name} for name in send_queues],
        },
        "lag_metric": {
            "name": "ApproximateAgeOfOldestMessage",
            "stat": CW_STAT_MAX,
            "period_seconds": CW_PERIOD_SECONDS,
            "dimensions": [{"QueueName": name} for name in persist_queues],
        },
        "preprocessing": {
            "window_preload_seconds": args.window_preload_seconds,
            "window_tail_seconds": args.window_tail_seconds,
            "repro_metric": args.repro_metric,
            "variance_threshold_percent": args.variance_threshold_percent,
            "min_active_periods": args.min_active_periods,
            "allow_peak_gate": args.allow_peak_gate,
        },
        "overlap_check": {
            "overlap_detected": bool(overlaps),
            "overlaps": overlaps,
        },
        "run_windows": [
            {
                "run_id": run.run_id,
                "profile": run.profile,
                "job_window_utc": f"{run.job_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}..{run.job_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                "query_window_utc": f"{run.query_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}..{run.query_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            }
            for run in run_windows
        ],
    }

    summary = {
        "completion_metric": args.repro_metric,
        "off_gate": off_gate,
        "on_gate": on_gate,
        "off_peak_rps_runs": [
            float(run["combined_peak_rps"])
            for run in metrics
            if run["profile"] == "off"
        ],
        "on_peak_rps_runs": [
            float(run["combined_peak_rps"]) for run in metrics if run["profile"] == "on"
        ],
        "variance_threshold_percent": args.variance_threshold_percent,
        "reproducible": reproducible,
    }

    (out_dir / "measurement_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    (out_dir / "benchmark_metrics_raw.json").write_text(
        json.dumps({"runs": metrics, "reproducibility": summary}, indent=2),
        encoding="utf-8",
    )
    first_off = next(
        run for run in run_windows if run.profile == "off" and run.run_id == "r1"
    )
    first_on = next(
        run for run in run_windows if run.profile == "on" and run.run_id == "r1"
    )
    (out_dir / "persist-off-window.txt").write_text(
        f"{first_off.query_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}..{first_off.query_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}\n",
        encoding="utf-8",
    )
    (out_dir / "persist-on-window.txt").write_text(
        f"{first_on.query_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}..{first_on.query_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}\n",
        encoding="utf-8",
    )
    if not reproducible:
        print(json.dumps(summary, indent=2))
        raise SystemExit(1)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
