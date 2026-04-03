"""Unit tests for P12.9 WS2 observability evidence parser."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "v3_p12_9_ws2_observability_evidence.py"
)


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "v3_p12_9_ws2_observability_evidence", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load WS2 observability evidence module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _shard_payload() -> dict[str, Any]:
    return {
        "receive_events_last_batch": 10,
        "receive_events_total": 100,
        "ingest_events_per_sec": 25.5,
        "flush_events_last_batch": 10,
        "flush_payload_bytes_last": 2000,
        "flush_duration_ms_last": 8,
        "ack_events_last_batch": 10,
        "ack_latency_ms_last": 2,
        "s3_put_retries": 0,
        "checkpoint_write_retries": 0,
        "ack_retries": 0,
        "buffered_events": 0,
        "oldest_buffer_age_ms": 0,
        "lag_to_durable_commit_ms_last": 150,
        "transport_oldest_age_ms_last": 300,
    }


@pytest.mark.unit
def test_extract_snapshot_payloads_from_logs() -> None:
    module = _load_module()
    text = (
        'INFO x writer_snapshot {"snapshot_emitted_at_ms": 1, "shards": {"0": {}}}\n'
        "INFO x ignore\n"
        'INFO x writer_snapshot {"snapshot_emitted_at_ms": 2, "shards": {"1": {}}}\n'
    )
    parsed = module._extract_snapshot_payloads(text)
    assert [item["snapshot_emitted_at_ms"] for item in parsed] == [1, 2]


@pytest.mark.unit
def test_build_report_passes_for_complete_shard_series() -> None:
    module = _load_module()
    snapshots = [
        {
            "snapshot_emitted_at_ms": ts,
            "shards": {"0": _shard_payload(), "1": _shard_payload()},
        }
        for ts in (1000, 2000, 3000)
    ]
    grouped = module._collect_by_shard(snapshots, active_shards=[0, 1])
    report = module._build_report(
        run_id="ws2-on-1",
        window_start_utc="2026-03-31T10:00:00Z",
        window_end_utc="2026-03-31T10:05:00Z",
        active_shards=[0, 1],
        shard_snapshots=grouped,
        min_snapshots=3,
    )
    assert report["pass"] is True
    assert report["missing_shards"] == []
    assert report["snapshot_counts_per_shard"][0] == 3


@pytest.mark.unit
def test_build_report_fails_when_fields_or_snapshots_missing() -> None:
    module = _load_module()
    bad_payload = _shard_payload()
    bad_payload.pop("ack_latency_ms_last")
    snapshots = [
        {"snapshot_emitted_at_ms": 1000, "shards": {"0": bad_payload}},
        {"snapshot_emitted_at_ms": 1500, "shards": {"0": bad_payload}},
    ]
    grouped = module._collect_by_shard(snapshots, active_shards=[0, 1])
    report = module._build_report(
        run_id="ws2-on-bad",
        window_start_utc="2026-03-31T11:00:00Z",
        window_end_utc="2026-03-31T11:05:00Z",
        active_shards=[0, 1],
        shard_snapshots=grouped,
        min_snapshots=3,
    )
    assert report["pass"] is False
    assert 1 in report["missing_shards"]
    assert "ack_latency_ms_last" in report["missing_fields_per_shard"][0]
