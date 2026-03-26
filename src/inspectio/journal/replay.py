"""Snapshot load + journal tail replay (§18.4)."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

from inspectio.journal.records import (
    JournalDecodeError,
    JournalRecordV1,
    parse_gzip_ndjson_segment,
)

log = logging.getLogger("inspectio.journal.replay")


@dataclass(frozen=True, slots=True)
class SnapshotShardV1:
    """Minimal snapshot shape for worker restart (§18.4)."""

    shard_id: int
    last_record_index: int
    pending: list[dict[str, Any]]


def _snapshot_key(shard_id: int) -> str:
    return f"state/snapshot/{shard_id:05d}/latest.json"


async def load_snapshot_if_present(
    s3_client: Any,
    bucket: str,
    shard_id: int,
) -> SnapshotShardV1 | None:
    """Load `latest.json` for a shard; return None if missing."""
    key = _snapshot_key(shard_id)
    try:
        resp = await s3_client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "NoSuchKey":
            return None
        raise
    body = await resp["Body"].read()
    data = json.loads(body.decode("utf-8"))
    return SnapshotShardV1(
        shard_id=int(data["shardId"]),
        last_record_index=int(data["lastRecordIndex"]),
        pending=list(data.get("pending", [])),
    )


async def load_max_record_index_for_shard(
    s3_client: Any,
    bucket: str,
    shard_id: int,
) -> int:
    """Scan journal segments for `shard_id` and return max `recordIndex` or -1."""
    prefix = f"state/journal/{shard_id:05d}/"
    max_idx = -1
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = await s3_client.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []) or []:
            key = obj["Key"]
            if not key.endswith(".ndjson.gz"):
                continue
            o = await s3_client.get_object(Bucket=bucket, Key=key)
            raw = await o["Body"].read()
            try:
                records = parse_gzip_ndjson_segment(raw)
            except JournalDecodeError:
                continue
            for r in records:
                max_idx = max(max_idx, r.record_index)
        if not resp.get("IsTruncated"):
            break
        token = resp.get("NextContinuationToken")
    return max_idx


async def load_max_record_index_parallel(
    s3_client: Any,
    bucket: str,
    shard_ids: list[int],
) -> dict[int, int]:
    """Load high-water marks for many shards (worker startup)."""

    async def one(sid: int) -> tuple[int, int]:
        return sid, await load_max_record_index_for_shard(s3_client, bucket, sid)

    results = await asyncio.gather(*[one(s) for s in shard_ids])
    return {sid: idx for sid, idx in results}


def replay_records_after_index(
    records: list[JournalRecordV1],
    last_record_index: int,
) -> list[JournalRecordV1]:
    """Filter records whose `recordIndex` is strictly greater than `last_record_index`."""
    return [r for r in records if r.record_index > last_record_index]
