"""P8 snapshot + tail replay logic (§18.4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from inspectio.journal.records import JournalRecordV1, parse_gzip_ndjson_segment


class SnapshotReplayError(RuntimeError):
    """Snapshot or tail replay cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class ReplayState:
    shard_id: int
    last_record_index: int
    active: dict[str, dict[str, Any]]


class ReplayS3Store:
    """S3-backed snapshot/tail loader for startup replay."""

    def __init__(self, *, s3_client: Any, bucket: str) -> None:
        self._s3_client = s3_client
        self._bucket = bucket

    async def load_latest(self, *, shard_id: int) -> ReplayState | None:
        key = f"state/snapshot/{shard_id}/latest.json"
        try:
            response = await self._s3_client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:  # pragma: no cover - provider-specific missing key
            if _is_missing_key_error(exc):
                return None
            raise SnapshotReplayError(f"failed reading snapshot: {exc}") from exc
        body = await response["Body"].read()
        return load_snapshot_json(body.decode("utf-8"))

    async def load_tail_segments(self, *, shard_id: int) -> list[bytes]:
        prefix = f"state/journal/{shard_id}/"
        try:
            response = await self._s3_client.list_objects_v2(
                Bucket=self._bucket,
                Prefix=prefix,
            )
        except Exception as exc:
            raise SnapshotReplayError(
                f"failed listing journal segments: {exc}"
            ) from exc
        keys = sorted([obj["Key"] for obj in response.get("Contents", [])])
        blobs: list[bytes] = []
        for key in keys:
            try:
                obj = await self._s3_client.get_object(Bucket=self._bucket, Key=key)
            except Exception as exc:
                raise SnapshotReplayError(
                    f"failed reading journal segment: {exc}"
                ) from exc
            blobs.append(await obj["Body"].read())
        return blobs


def load_snapshot_json(raw_json: str) -> ReplayState:
    try:
        obj = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise SnapshotReplayError(str(exc)) from exc
    try:
        return ReplayState(
            shard_id=int(obj["shardId"]),
            last_record_index=int(obj["lastRecordIndex"]),
            active={str(k): dict(v) for k, v in dict(obj["active"]).items()},
        )
    except Exception as exc:  # pragma: no cover - defensive shape validation
        raise SnapshotReplayError(f"invalid snapshot shape: {exc}") from exc


def apply_tail_records(
    *, snapshot: ReplayState, gzip_segments: list[bytes]
) -> ReplayState:
    active = dict(snapshot.active)
    max_record_index = snapshot.last_record_index
    for blob in gzip_segments:
        try:
            records = parse_gzip_ndjson_segment(blob)
        except Exception as exc:
            raise SnapshotReplayError(f"tail replay failed: {exc}") from exc
        for record in records:
            if record.shard_id != snapshot.shard_id:
                continue
            if record.record_index <= snapshot.last_record_index:
                continue
            _apply_record(active, record)
            max_record_index = max(max_record_index, record.record_index)
    return ReplayState(
        shard_id=snapshot.shard_id,
        last_record_index=max_record_index,
        active=active,
    )


def _apply_record(active: dict[str, dict[str, Any]], record: JournalRecordV1) -> None:
    if record.type == "INGEST_APPLIED":
        state = active.setdefault(record.message_id, {})
        state.setdefault("messageId", record.message_id)
        state.setdefault("attemptCount", 0)
        state.setdefault("status", "pending")
        state.setdefault("nextDueAtMs", int(record.payload["receivedAtMs"]))
        return
    if record.type == "NEXT_DUE":
        active[record.message_id] = {
            "messageId": record.message_id,
            "attemptCount": int(record.payload["attemptCount"]),
            "nextDueAtMs": int(record.payload["nextDueAtMs"]),
            "status": "pending",
        }
        return
    if record.type == "TERMINAL":
        active.pop(record.message_id, None)


def _is_missing_key_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "nosuchkey" in text or "not found" in text or "404" in text
