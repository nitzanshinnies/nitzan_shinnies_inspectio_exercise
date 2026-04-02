"""P12.9 WS2: validate writer snapshot completeness from raw logs."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WRITER_SNAPSHOT_PREFIX = "writer_snapshot "
DEFAULT_MIN_SNAPSHOTS = 3
REQUIRED_SHARD_FIELDS: tuple[str, ...] = (
    "receive_events_last_batch",
    "receive_events_total",
    "ingest_events_per_sec",
    "flush_events_last_batch",
    "flush_payload_bytes_last",
    "flush_duration_ms_last",
    "ack_events_last_batch",
    "ack_latency_ms_last",
    "s3_put_retries",
    "checkpoint_write_retries",
    "ack_retries",
    "buffered_events",
    "oldest_buffer_age_ms",
    "lag_to_durable_commit_ms_last",
    "transport_oldest_age_ms_last",
)


@dataclass(slots=True)
class ShardValidation:
    snapshot_count: int
    missing_fields: list[str]
    timestamps_monotonic: bool


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--window-start-utc", required=True)
    parser.add_argument("--window-end-utc", required=True)
    parser.add_argument("--active-shards", required=True)
    parser.add_argument("--log-paths", nargs="+", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-snapshots", type=int, default=DEFAULT_MIN_SNAPSHOTS)
    return parser.parse_args()


def _active_shards(raw: str) -> list[int]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return [int(item) for item in values]


def _extract_snapshot_payloads(log_text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in log_text.splitlines():
        marker_index = line.find(WRITER_SNAPSHOT_PREFIX)
        if marker_index < 0:
            continue
        payload = line[marker_index + len(WRITER_SNAPSHOT_PREFIX) :].strip()
        if not payload:
            continue
        out.append(json.loads(payload))
    return out


def _collect_by_shard(
    snapshots: list[dict[str, Any]],
    *,
    active_shards: list[int],
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in snapshots:
        timestamp_ms = int(snapshot.get("snapshot_emitted_at_ms", 0))
        shard_map = snapshot.get("shards", {})
        for shard in active_shards:
            shard_payload = shard_map.get(str(shard))
            if shard_payload is None:
                continue
            grouped[shard].append(
                {"timestamp_ms": timestamp_ms, "payload": shard_payload}
            )
    return grouped


def _validate_shard_series(
    shard_snapshots: list[dict[str, Any]],
    *,
    min_snapshots: int,
) -> ShardValidation:
    timestamps = [int(item.get("timestamp_ms", 0)) for item in shard_snapshots]
    timestamps_monotonic = all(
        timestamps[i] > timestamps[i - 1] for i in range(1, len(timestamps))
    )
    missing_fields: set[str] = set()
    for item in shard_snapshots:
        payload = item["payload"]
        for field_name in REQUIRED_SHARD_FIELDS:
            if field_name not in payload:
                missing_fields.add(field_name)
    if len(shard_snapshots) < min_snapshots:
        missing_fields.add(f"min_snapshots<{min_snapshots}")
    return ShardValidation(
        snapshot_count=len(shard_snapshots),
        missing_fields=sorted(missing_fields),
        timestamps_monotonic=timestamps_monotonic,
    )


def _build_report(
    *,
    run_id: str,
    window_start_utc: str,
    window_end_utc: str,
    active_shards: list[int],
    shard_snapshots: dict[int, list[dict[str, Any]]],
    min_snapshots: int,
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    missing_shards: list[int] = []
    pass_all = True
    for shard in active_shards:
        series = shard_snapshots.get(shard, [])
        if not series:
            missing_shards.append(shard)
        validated = _validate_shard_series(series, min_snapshots=min_snapshots)
        shard_pass = validated.timestamps_monotonic and not validated.missing_fields
        if not shard_pass:
            pass_all = False
        summary[str(shard)] = {
            "snapshot_count": validated.snapshot_count,
            "timestamps_monotonic": validated.timestamps_monotonic,
            "missing_fields": validated.missing_fields,
            "pass": shard_pass,
        }
    if missing_shards:
        pass_all = False
    return {
        "run_id": run_id,
        "window_utc": {"start": window_start_utc, "end": window_end_utc},
        "active_shards": active_shards,
        "min_snapshots_required": min_snapshots,
        "snapshot_counts_per_shard": {
            shard: summary[str(shard)]["snapshot_count"] for shard in active_shards
        },
        "missing_fields_per_shard": {
            shard: summary[str(shard)]["missing_fields"] for shard in active_shards
        },
        "missing_shards": missing_shards,
        "shards": summary,
        "pass": pass_all,
    }


def _summary_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# WS2 Observability Completeness Summary",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- window: `{report['window_utc']['start']}` -> `{report['window_utc']['end']}`",
        f"- min_snapshots_required: `{report['min_snapshots_required']}`",
        f"- missing_shards: `{report['missing_shards']}`",
        f"- pass: `{report['pass']}`",
        "",
        "| shard | snapshots | monotonic_ts | missing_fields | pass |",
        "| --- | ---: | :---: | --- | :---: |",
    ]
    for shard in report["active_shards"]:
        shard_row = report["shards"][str(shard)]
        missing = ", ".join(shard_row["missing_fields"]) or "-"
        lines.append(
            f"| {shard} | {shard_row['snapshot_count']} | "
            f"{'yes' if shard_row['timestamps_monotonic'] else 'no'} | "
            f"{missing} | {'yes' if shard_row['pass'] else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = _parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    active_shards = _active_shards(args.active_shards)
    snapshots: list[dict[str, Any]] = []
    for log_path in args.log_paths:
        snapshots.extend(_extract_snapshot_payloads(Path(log_path).read_text()))
    snapshots.sort(key=lambda item: int(item.get("snapshot_emitted_at_ms", 0)))
    shard_snapshots = _collect_by_shard(snapshots, active_shards=active_shards)
    report = _build_report(
        run_id=args.run_id,
        window_start_utc=args.window_start_utc,
        window_end_utc=args.window_end_utc,
        active_shards=active_shards,
        shard_snapshots=shard_snapshots,
        min_snapshots=args.min_snapshots,
    )
    (output_dir / "completeness_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "completeness_summary.md").write_text(_summary_markdown(report))
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
