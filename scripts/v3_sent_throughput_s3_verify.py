#!/usr/bin/env python3
"""Admit N messages via L1, wait for SQS drain, verify S3 terminal success count.

Run in-cluster (Job) with IRSA or node creds. Env:

- INSPECTIO_VERIFY_API_BASE (default http://inspectio-l1:8080)
- INSPECTIO_VERIFY_TOTAL_MESSAGES (required, e.g. 10000)
- INSPECTIO_VERIFY_BATCH (default 100)
- INSPECTIO_VERIFY_CONCURRENCY (default 20)
- INSPECTIO_VERIFY_DRAIN_TIMEOUT_SEC (default 1200)
- INSPECTIO_VERIFY_POLL_SEC (default 5)
- INSPECTIO_V3_PERSISTENCE_S3_BUCKET (required)
- AWS_DEFAULT_REGION (default us-east-1)
- INSPECTIO_V3_BULK_QUEUE_URL, INSPECTIO_V3_SEND_QUEUE_URLS (all shards), INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URL(S)
- INSPECTIO_V3_PERSISTENCE_S3_PREFIX (default state); optional INSPECTIO_VERIFY_WRITER_SHARD_COUNT
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import sys
import time
from typing import Any

import boto3
import httpx
from botocore.exceptions import ClientError


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return int(str(raw).strip())


def _queue_depth(client: Any, url: str) -> int:
    resp = client.get_queue_attributes(
        QueueUrl=url,
        AttributeNames=[
            "ApproximateNumberOfMessages",
            "ApproximateNumberOfMessagesNotVisible",
        ],
    )
    attrs = resp.get("Attributes", {})
    vis = int(attrs.get("ApproximateNumberOfMessages", "0"))
    inv = int(attrs.get("ApproximateNumberOfMessagesNotVisible", "0"))
    return vis + inv


def _all_send_queue_urls() -> list[str]:
    raw = os.environ.get("INSPECTIO_V3_SEND_QUEUE_URLS", "").strip()
    if raw.startswith("["):
        urls = [str(u) for u in json.loads(raw)]
        if urls:
            return urls
    single = os.environ.get("INSPECTIO_V3_WORKER_SEND_QUEUE_URL", "").strip()
    return [single] if single else []


def _all_persist_transport_queue_urls() -> list[str]:
    raw = os.environ.get("INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URLS", "").strip()
    if raw.startswith("["):
        urls = [str(u) for u in json.loads(raw)]
        if urls:
            return urls
    single = os.environ.get("INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URL", "").strip()
    return [single] if single else []


def _writer_shard_count() -> int:
    override = _env_int("INSPECTIO_VERIFY_WRITER_SHARD_COUNT", 0)
    if override > 0:
        return override
    n = _env_int("INSPECTIO_V3_PERSIST_TRANSPORT_SHARD_COUNT", 0)
    if n > 0:
        return n
    urls = _all_persist_transport_queue_urls()
    if urls:
        return len(urls)
    return 1


def _s3_prefix() -> str:
    return (
        os.environ.get("INSPECTIO_V3_PERSISTENCE_S3_PREFIX", "state").strip().strip("/")
    )


def _checkpoint_next_segment_seq(
    s3: Any,
    *,
    bucket: str,
    logical_prefix: str,
    shard: int,
) -> int | None:
    key = f"{logical_prefix}/checkpoints/{shard}/latest.json"
    try:
        raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    data = json.loads(raw.decode("utf-8"))
    return int(data.get("nextSegmentSeq", 0))


def _parse_segment_seq_from_key(key: str) -> int | None:
    name = key.rsplit("/", 1)[-1]
    if not name.endswith(".ndjson.gz"):
        return None
    stem = name[: -len(".ndjson.gz")]
    try:
        return int(stem)
    except ValueError:
        return None


async def _admit_phase(
    *,
    base: str,
    total: int,
    batch: int,
    concurrency: int,
) -> tuple[str, int, float, int]:
    run_tag = f"sent-verify-{time.time_ns()}"
    work: asyncio.Queue[int] = asyncio.Queue()
    left = total
    while left > 0:
        b = min(batch, left)
        await work.put(b)
        left -= b

    admitted = 0
    transient = 0
    lock = asyncio.Lock()

    limits = httpx.Limits(
        max_connections=max(concurrency + 8, 32),
        max_keepalive_connections=max(concurrency + 8, 32),
    )
    timeout = httpx.Timeout(120.0)
    t0 = time.perf_counter()

    async def worker(client: httpx.AsyncClient) -> None:
        nonlocal admitted, transient
        while True:
            try:
                this_batch = work.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                r = await client.post(
                    f"{base}/messages/repeat",
                    params={"count": this_batch},
                    json={"body": run_tag},
                )
                r.raise_for_status()
                data = r.json()
                got = int(data.get("accepted", 0))
                if got != this_batch:
                    raise RuntimeError(
                        f"accepted mismatch want={this_batch} got={data!r}"
                    )
            except Exception:
                await work.put(this_batch)
                async with lock:
                    transient += 1
                await asyncio.sleep(0.05)
                continue
            async with lock:
                admitted += got

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        r = await client.get(f"{base}/healthz", timeout=30.0)
        r.raise_for_status()
        await asyncio.gather(
            *[asyncio.create_task(worker(client)) for _ in range(max(1, concurrency))],
        )

    elapsed = time.perf_counter() - t0
    return run_tag, admitted, elapsed, transient


def _drain_queues(
    *,
    bulk_url: str,
    send_urls: list[str],
    persist_urls: list[str],
    timeout_sec: int,
    poll_sec: float,
) -> tuple[float, bool]:
    sqs = boto3.client(
        "sqs", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    )
    deadline = time.monotonic() + timeout_sec
    t0 = time.monotonic()
    while time.monotonic() < deadline:
        d_bulk = _queue_depth(sqs, bulk_url)
        d_send = sum(_queue_depth(sqs, u) for u in send_urls)
        d_persist = sum(_queue_depth(sqs, u) for u in persist_urls)
        if d_bulk + d_send + d_persist == 0:
            return time.monotonic() - t0, True
        time.sleep(poll_sec)
    return time.monotonic() - t0, False


def _checkpoint_next_seq_tuple(
    s3: Any,
    *,
    bucket: str,
    logical_prefix: str,
    n_shards: int,
) -> tuple[int, ...]:
    out: list[int] = []
    for shard in range(n_shards):
        nxt = _checkpoint_next_segment_seq(
            s3,
            bucket=bucket,
            logical_prefix=logical_prefix,
            shard=shard,
        )
        out.append(-1 if nxt is None else int(nxt))
    return tuple(out)


def _wait_checkpoint_stable_after_drain(
    *,
    bucket: str,
    logical_prefix: str,
    region: str,
    n_shards: int,
    timeout_sec: int,
    poll_sec: float,
    stable_rounds: int,
) -> tuple[float, bool]:
    """SQS can be empty while the persistence writer still flushes to S3; wait for quiet checkpoints."""

    s3 = boto3.client("s3", region_name=region)
    deadline = time.monotonic() + timeout_sec
    t0 = time.monotonic()
    prev: tuple[int, ...] | None = None
    stable = 0
    while time.monotonic() < deadline:
        now = _checkpoint_next_seq_tuple(
            s3,
            bucket=bucket,
            logical_prefix=logical_prefix,
            n_shards=n_shards,
        )
        if prev is not None and now == prev:
            stable += 1
            if stable >= stable_rounds:
                return time.monotonic() - t0, True
        else:
            stable = 0
        prev = now
        time.sleep(poll_sec)
    return time.monotonic() - t0, False


def _count_terminal_success_s3(
    *,
    bucket: str,
    run_tag: str,
    region: str,
    logical_prefix: str,
    min_segment_seq_by_shard: list[int],
) -> tuple[int, set[str]]:
    s3 = boto3.client("s3", region_name=region)
    paginator = s3.get_paginator("list_objects_v2")
    unique_mids: set[str] = set()
    lines_scanned = 0
    for shard, min_seq in enumerate(min_segment_seq_by_shard):
        prefix = f"{logical_prefix}/events/{shard}/"
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if min_seq > 0:
            start_after = f"{prefix}{min_seq - 1:020d}.ndjson.gz"
            kwargs["StartAfter"] = start_after
        for page in paginator.paginate(**kwargs):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                seq = _parse_segment_seq_from_key(key)
                if seq is None or seq < min_seq:
                    continue
                raw = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
                try:
                    text = gzip.decompress(raw).decode("utf-8")
                except OSError:
                    text = raw.decode("utf-8")
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    lines_scanned += 1
                    ev = json.loads(line)
                    if ev.get("eventType") != "terminal":
                        continue
                    if ev.get("status") != "success":
                        continue
                    body = ev.get("body") or ""
                    if run_tag not in body:
                        continue
                    mid = ev.get("messageId")
                    if mid:
                        unique_mids.add(str(mid))
    return lines_scanned, unique_mids


def main() -> int:
    run_started = time.perf_counter()
    base = os.environ.get(
        "INSPECTIO_VERIFY_API_BASE", "http://inspectio-l1:8080"
    ).rstrip(
        "/",
    )
    total = _env_int("INSPECTIO_VERIFY_TOTAL_MESSAGES", 0)
    if total <= 0:
        print("INSPECTIO_VERIFY_TOTAL_MESSAGES must be set and > 0", file=sys.stderr)
        return 2
    batch = max(1, _env_int("INSPECTIO_VERIFY_BATCH", 100))
    conc = max(1, _env_int("INSPECTIO_VERIFY_CONCURRENCY", 20))
    drain_timeout = max(60, _env_int("INSPECTIO_VERIFY_DRAIN_TIMEOUT_SEC", 1200))
    poll_sec = float(os.environ.get("INSPECTIO_VERIFY_POLL_SEC", "5"))

    bucket = os.environ.get("INSPECTIO_V3_PERSISTENCE_S3_BUCKET", "").strip()
    if not bucket:
        print("INSPECTIO_V3_PERSISTENCE_S3_BUCKET required", file=sys.stderr)
        return 2
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    logical_prefix = _s3_prefix()
    bulk_url = os.environ.get("INSPECTIO_V3_BULK_QUEUE_URL", "").strip()
    persist_urls = _all_persist_transport_queue_urls()
    send_urls = _all_send_queue_urls()
    if not bulk_url or not send_urls or not persist_urls:
        print("Bulk/send/persist queue URLs required in env", file=sys.stderr)
        return 2

    s3_pre = boto3.client("s3", region_name=region)
    n_shards = _writer_shard_count()
    min_seq_snapshot: list[int] = []
    for shard in range(n_shards):
        nxt = _checkpoint_next_segment_seq(
            s3_pre,
            bucket=bucket,
            logical_prefix=logical_prefix,
            shard=shard,
        )
        min_seq_snapshot.append(0 if nxt is None else int(nxt))
    print(
        json.dumps(
            {
                "phase": "s3_checkpoint_snapshot",
                "logical_prefix": logical_prefix,
                "writer_shard_count": n_shards,
                "min_segment_seq_per_shard": min_seq_snapshot,
            },
            sort_keys=True,
        ),
    )

    run_tag, admitted, admit_sec, transient = asyncio.run(
        _admit_phase(base=base, total=total, batch=batch, concurrency=conc),
    )
    msg_per_sec = admitted / admit_sec if admit_sec > 0 else 0.0
    print(
        json.dumps(
            {
                "phase": "admit",
                "run_tag": run_tag,
                "target_messages": total,
                "admitted_messages": admitted,
                "admit_wall_sec": round(admit_sec, 3),
                "throughput_messages_per_sec": round(msg_per_sec, 2),
                "transient_http_errors": transient,
            },
            sort_keys=True,
        ),
    )

    drain_sec, drained = _drain_queues(
        bulk_url=bulk_url,
        send_urls=send_urls,
        persist_urls=persist_urls,
        timeout_sec=drain_timeout,
        poll_sec=poll_sec,
    )
    print(
        json.dumps(
            {
                "phase": "drain",
                "drain_wait_sec": round(drain_sec, 3),
                "all_queues_empty": drained,
            },
            sort_keys=True,
        ),
    )
    if not drained:
        print(
            "VERIFY_FAIL queues not empty before S3 scan; increase drain timeout or scale workers",
            file=sys.stderr,
        )
        return 1

    cp_stable_timeout = max(
        60, _env_int("INSPECTIO_VERIFY_CHECKPOINT_STABLE_TIMEOUT_SEC", 900)
    )
    cp_stable_poll = float(
        os.environ.get("INSPECTIO_VERIFY_CHECKPOINT_STABLE_POLL_SEC", "10")
    )
    cp_stable_rounds = max(2, _env_int("INSPECTIO_VERIFY_CHECKPOINT_STABLE_ROUNDS", 4))
    quiet_sec, quiet_ok = _wait_checkpoint_stable_after_drain(
        bucket=bucket,
        logical_prefix=logical_prefix,
        region=region,
        n_shards=n_shards,
        timeout_sec=cp_stable_timeout,
        poll_sec=cp_stable_poll,
        stable_rounds=cp_stable_rounds,
    )
    print(
        json.dumps(
            {
                "phase": "checkpoint_stable",
                "checkpoint_stable_ok": quiet_ok,
                "checkpoint_stable_wait_sec": round(quiet_sec, 3),
            },
            sort_keys=True,
        ),
    )
    if not quiet_ok:
        print(
            "VERIFY_FAIL S3 checkpoints still moving after drain; increase "
            "INSPECTIO_VERIFY_CHECKPOINT_STABLE_TIMEOUT_SEC or scale persistence-writer",
            file=sys.stderr,
        )
        return 1

    lines_scanned, unique_mids = _count_terminal_success_s3(
        bucket=bucket,
        run_tag=run_tag,
        region=region,
        logical_prefix=logical_prefix,
        min_segment_seq_by_shard=min_seq_snapshot,
    )
    sent_count = len(unique_mids)
    ok = sent_count == admitted == total
    total_wall = time.perf_counter() - run_started
    e2e_rps = admitted / total_wall if total_wall > 0 else 0.0
    print(
        json.dumps(
            {
                "phase": "s3_terminal_success",
                "s3_lines_scanned": lines_scanned,
                "unique_message_ids_terminal_success": sent_count,
                "expected_messages": total,
                "admitted_messages": admitted,
                "all_sent_persisted_match": ok,
            },
            sort_keys=True,
        ),
    )
    print(
        json.dumps(
            {
                "phase": "summary",
                "admit_throughput_messages_per_sec": round(msg_per_sec, 2),
                "end_to_end_throughput_messages_per_sec": round(e2e_rps, 2),
                "total_wall_sec": round(total_wall, 3),
                "admit_wall_sec": round(admit_sec, 3),
                "drain_wall_sec": round(drain_sec, 3),
            },
            sort_keys=True,
        ),
    )
    if not ok:
        print(
            f"VERIFY_FAIL admitted={admitted} total_target={total} terminal_success_unique={sent_count}",
            file=sys.stderr,
        )
        return 1
    print(
        "VERIFY_OK all admitted messages have terminal success in S3 for this run_tag"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
