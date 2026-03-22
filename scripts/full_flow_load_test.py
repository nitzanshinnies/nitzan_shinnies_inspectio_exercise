#!/usr/bin/env python3
"""Full-stack load test via the same REST paths the operational UI uses.

Submits large batches with ``POST /messages/repeat`` (same JSON body shape as the
frontend), waits until no pending lifecycle objects remain under ``LOCAL_S3_ROOT``,
then:

1. Calls the health monitor ``POST /internal/v1/integrity-check``.
2. Counts JSON objects on disk under ``state/success``, ``state/failed``,
   ``state/pending``, and ``state/notifications`` and checks invariants.

**Scale / mock audit:** the health monitor compares **all** lifecycle keys to a
**bounded** mock SMS audit window (``AUDIT_SENDS_MAX_LIMIT``). For tens of
thousands of messages you must raise both the mock ring buffer and audit fetch
cap, and usually set ``INSPECTIO_MOCK_FAILURE_RATE=0`` so sends per message stay
~1. Example before ``docker compose up``::

    export INSPECTIO_MOCK_FAILURE_RATE=0
    export INSPECTIO_MOCK_AUDIT_LOG_MAX_ENTRIES=500000
    export INSPECTIO_MOCK_AUDIT_SENDS_MAX_LIMIT=250000

Restart **mock-sms** and **health-monitor** after changing mock env (both import
``mock_sms.config`` at process start).

**In-memory persistence (faster ``list_prefix``):** start the stack with the
compose override so persistence uses ``INSPECTIO_LOCAL_S3_STORAGE=memory`` (see
``docker-compose.memory-s3.yml``). Then run this script with ``--in-memory-s3``.
Drain detection uses ``POST /internal/v1/list-prefix`` (not the host tree); after
each drain the script calls ``POST /internal/v1/flush-to-disk`` so disk
invariants and ``--local-s3-root`` inspection match memory state.

Usage::

    pip install -e ".[dev]"
    docker compose -f docker-compose.yml -f docker-compose.memory-s3.yml up -d
    python scripts/full_flow_load_test.py \\
        --api-base http://127.0.0.1:3000 \\
        --health-monitor-base http://127.0.0.1:8003 \\
        --local-s3-root ./.local-s3 \\
        --in-memory-s3

File-backed persistence (default compose)::

    python scripts/full_flow_load_test.py \\
        --api-base http://127.0.0.1:3000 \\
        --health-monitor-base http://127.0.0.1:8003 \\
        --local-s3-root ./.local-s3

When the API is reached directly (no nginx), pass ``--api-base http://127.0.0.1:8000``.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_API_BASE: str = "http://127.0.0.1:3000"
DEFAULT_DRAIN_POLL_SEC: float = 2.0
DEFAULT_DRAIN_TIMEOUT_SEC: float = 7200.0
DEFAULT_HEALTH_MONITOR_BASE: str = "http://127.0.0.1:8003"
DEFAULT_HTTP_TIMEOUT_SEC: float = 120.0
DEFAULT_INTEGRITY_TIMEOUT_SEC: float = 900.0
DEFAULT_LOCAL_S3_ROOT: str = "./.local-s3"
DEFAULT_PERSISTENCE_BASE: str = "http://127.0.0.1:8001"
DEFAULT_REPEAT_CHUNK_MAX: int = 10_000
DEFAULT_SIZES: tuple[int, ...] = (10_000, 20_000, 30_000)
HEADER_INTEGRITY_CHECK_TOKEN: str = "X-Integrity-Check-Token"
PENDING_PREFIX: str = "state/pending/"


@dataclass(frozen=True)
class LifecycleDiskCounts:
    failed: int
    notifications: int
    pending: int
    success: int

    @property
    def terminals(self) -> int:
        return self.success + self.failed


def parse_sizes_csv(raw: str) -> tuple[int, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("at least one batch size is required")
    return tuple(int(p, 10) for p in parts)


def count_json_files(root: Path, relative_subdir: str) -> int:
    base = root / relative_subdir
    if not base.is_dir():
        return 0
    return sum(1 for p in base.rglob("*.json") if p.is_file())


def scan_local_s3(root: Path) -> LifecycleDiskCounts:
    return LifecycleDiskCounts(
        failed=count_json_files(root, "state/failed"),
        notifications=count_json_files(root, "state/notifications"),
        pending=count_json_files(root, "state/pending"),
        success=count_json_files(root, "state/success"),
    )


def submit_repeat_batch(
    client: httpx.Client,
    api_base: str,
    count: int,
    chunk_max: int,
    message_body: str,
    request_timeout_sec: float,
) -> int:
    if count < 1:
        return 0
    if chunk_max < 1:
        raise ValueError("chunk_max must be >= 1")
    total_accepted = 0
    remaining = count
    while remaining > 0:
        chunk = min(chunk_max, remaining)
        url = f"{api_base.rstrip('/')}/messages/repeat"
        response = client.post(
            url,
            params={"count": chunk},
            json={
                "body": message_body,
                "shouldFail": False,
            },
            timeout=request_timeout_sec,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        accepted = int(payload["accepted"])
        total_accepted += accepted
        if accepted != chunk:
            raise RuntimeError(
                f"repeat accepted {accepted} messages, expected {chunk}: {payload!r}"
            )
        remaining -= chunk
        logger.info("submitted chunk accepted=%s (remaining in batch=%s)", accepted, remaining)
    return total_accepted


def wait_for_pending_zero(
    root: Path,
    poll_sec: float,
    timeout_sec: float,
) -> None:
    deadline = time.monotonic() + timeout_sec
    last = -1
    while time.monotonic() < deadline:
        pending = count_json_files(root, "state/pending")
        if pending == 0:
            logger.info("drain complete: no pending JSON objects under state/pending")
            return
        if pending != last:
            logger.info("waiting for drain: pending_json=%s", pending)
            last = pending
        time.sleep(poll_sec)
    pending = count_json_files(root, "state/pending")
    raise TimeoutError(
        f"timed out after {timeout_sec}s with pending_json={pending} under {root / 'state/pending'}"
    )


def persistence_has_pending_objects(
    client: httpx.Client,
    persistence_base: str,
    request_timeout_sec: float,
) -> bool:
    """True if persistence still has at least one key under ``state/pending/`` (``max_keys=1``)."""
    url = f"{persistence_base.rstrip('/')}/internal/v1/list-prefix"
    response = client.post(
        url,
        json={"prefix": PENDING_PREFIX, "max_keys": 1},
        timeout=request_timeout_sec,
    )
    response.raise_for_status()
    payload = response.json()
    keys = payload.get("keys")
    if not isinstance(keys, list):
        raise RuntimeError(f"list-prefix response missing keys list: {payload!r}")
    return len(keys) > 0


def wait_for_pending_zero_via_persistence(
    client: httpx.Client,
    persistence_base: str,
    poll_sec: float,
    timeout_sec: float,
    request_timeout_sec: float,
) -> None:
    deadline = time.monotonic() + timeout_sec
    last_busy: bool | None = None
    while time.monotonic() < deadline:
        if not persistence_has_pending_objects(
            client, persistence_base, request_timeout_sec=request_timeout_sec
        ):
            logger.info("drain complete: no pending objects in persistence (list-prefix)")
            return
        if last_busy is not True:
            logger.info("waiting for drain: persistence still has pending keys")
            last_busy = True
        time.sleep(poll_sec)
    raise TimeoutError(
        f"timed out after {timeout_sec}s waiting for pending=0 via persistence at {persistence_base!r}"
    )


def post_flush_to_disk(
    client: httpx.Client,
    persistence_base: str,
    *,
    root_override: str | None,
    request_timeout_sec: float,
) -> None:
    """Snapshot memory backend to disk (default root from persistence ``LOCAL_S3_ROOT``)."""
    url = f"{persistence_base.rstrip('/')}/internal/v1/flush-to-disk"
    body: dict[str, str] = {}
    if root_override:
        body["root"] = root_override
    response = client.post(url, json=body, timeout=request_timeout_sec)
    if response.status_code == 501:
        raise RuntimeError(
            "flush-to-disk returned 501 — persistence is not using the in-memory backend "
            "(set INSPECTIO_LOCAL_S3_STORAGE=memory and use docker-compose.memory-s3.yml)."
        )
    response.raise_for_status()


def post_integrity_check(
    client: httpx.Client,
    health_base: str,
    token: str | None,
    timeout_sec: float,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if token:
        headers[HEADER_INTEGRITY_CHECK_TOKEN] = token
    url = f"{health_base.rstrip('/')}/internal/v1/integrity-check"
    response = client.post(url, json={}, headers=headers, timeout=timeout_sec)
    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(
            f"integrity-check non-JSON body status={response.status_code} text={response.text[:500]!r}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"integrity-check JSON must be an object, got {type(data).__name__}")
    return data


def assert_integrity_ok(data: dict[str, Any]) -> None:
    violations = data.get("violations")
    if not isinstance(violations, list):
        raise AssertionError(f"integrity response missing violations list: {data!r}")
    if violations:
        preview = violations[:5]
        raise AssertionError(
            f"integrity check failed ok={data.get('ok')!r} violations={len(violations)} preview={preview!r}"
        )
    if data.get("ok") is not True:
        raise AssertionError(f"integrity check ok is not True: {data!r}")


def validate_disk_invariants(
    *,
    root: Path,
    cumulative_messages: int,
    counts: LifecycleDiskCounts,
    baseline: LifecycleDiskCounts,
) -> None:
    if counts.pending != 0:
        raise AssertionError(
            f"expected no pending JSON after drain, got pending={counts.pending} (root={root})"
        )
    delta_terminal = counts.terminals - baseline.terminals
    if delta_terminal != cumulative_messages:
        raise AssertionError(
            "terminal JSON delta mismatch vs cumulative API accepts: "
            f"success={counts.success} failed={counts.failed} "
            f"baseline_terminals={baseline.terminals} "
            f"delta_terminals={delta_terminal} cumulative_accepted={cumulative_messages}"
        )
    delta_notifications = counts.notifications - baseline.notifications
    if delta_notifications != delta_terminal:
        raise AssertionError(
            "notification JSON delta should match terminal delta: "
            f"delta_notifications={delta_notifications} delta_terminals={delta_terminal}"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load-test Inspectio via public API + health monitor + local S3 tree.",
    )
    parser.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE,
        help="Public API base (use nginx :3000 or API :8000).",
    )
    parser.add_argument(
        "--health-monitor-base",
        default=DEFAULT_HEALTH_MONITOR_BASE,
        help="Health monitor base URL.",
    )
    parser.add_argument(
        "--local-s3-root",
        default=DEFAULT_LOCAL_S3_ROOT,
        type=Path,
        help="Host path to LOCAL_S3_ROOT (same as persistence volume mount).",
    )
    parser.add_argument(
        "--persistence-base",
        default=DEFAULT_PERSISTENCE_BASE,
        help="Persistence service base URL (for --in-memory-s3 drain + flush).",
    )
    parser.add_argument(
        "--in-memory-s3",
        action="store_true",
        help=(
            "Drain via persistence list-prefix; flush to disk before disk scans "
            "(compose: add docker-compose.memory-s3.yml)."
        ),
    )
    parser.add_argument(
        "--flush-root",
        default=None,
        help=(
            "Optional JSON root for flush-to-disk when it must differ from persistence "
            "LOCAL_S3_ROOT (container path); omit for default."
        ),
    )
    parser.add_argument(
        "--integrity-token",
        default=None,
        help="Optional INTEGRITY_CHECK_TOKEN value for X-Integrity-Check-Token header.",
    )
    parser.add_argument(
        "--sizes",
        default=",".join(str(s) for s in DEFAULT_SIZES),
        help=f"Comma-separated batch sizes (default {','.join(str(s) for s in DEFAULT_SIZES)}).",
    )
    parser.add_argument(
        "--repeat-chunk-max",
        type=int,
        default=DEFAULT_REPEAT_CHUNK_MAX,
        help="Max count per POST /messages/repeat (must be <= server REPEAT_COUNT_MAX).",
    )
    parser.add_argument(
        "--http-timeout-sec",
        type=float,
        default=DEFAULT_HTTP_TIMEOUT_SEC,
        help="Timeout for API repeat posts.",
    )
    parser.add_argument(
        "--integrity-timeout-sec",
        type=float,
        default=DEFAULT_INTEGRITY_TIMEOUT_SEC,
        help="Timeout for POST /internal/v1/integrity-check (large trees are slow).",
    )
    parser.add_argument(
        "--drain-timeout-sec",
        type=float,
        default=DEFAULT_DRAIN_TIMEOUT_SEC,
        help="Max seconds to wait for pending/*.json to reach zero after a batch.",
    )
    parser.add_argument(
        "--drain-poll-sec",
        type=float,
        default=DEFAULT_DRAIN_POLL_SEC,
        help="Sleep between pending-count polls while draining.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse args and print the plan without calling services.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    sizes = parse_sizes_csv(args.sizes)
    root = args.local_s3_root.expanduser().resolve()

    logger.info(
        "plan batches=%s cumulative=%s api=%s health_monitor=%s local_s3_root=%s "
        "chunk_max=%s in_memory_s3=%s persistence_base=%s",
        sizes,
        sum(sizes),
        args.api_base,
        args.health_monitor_base,
        root,
        args.repeat_chunk_max,
        args.in_memory_s3,
        args.persistence_base,
    )
    if args.dry_run:
        return 0

    if not root.is_dir():
        raise SystemExit(f"LOCAL_S3_ROOT is not a directory: {root}")

    baseline = scan_local_s3(root)
    logger.info(
        "baseline disk terminals=%s notifications=%s pending=%s (success=%s failed=%s)",
        baseline.terminals,
        baseline.notifications,
        baseline.pending,
        baseline.success,
        baseline.failed,
    )
    if baseline.terminals > 0 or baseline.notifications > 0:
        logger.warning(
            "Non-empty S3 state at start — integrity-check may fail for older terminals "
            "outside the mock audit window. For a clean 60k-scale run, remove "
            "%s before starting (and restart the stack if needed).",
            root / "state",
        )

    cumulative = 0
    with httpx.Client() as client:
        for i, batch in enumerate(sizes, start=1):
            body = f"load-test batch {i} t={int(time.time())}"
            logger.info("--- batch %s size=%s body=%r ---", i, batch, body)
            t0 = time.perf_counter()
            accepted = submit_repeat_batch(
                client,
                api_base=args.api_base,
                count=batch,
                chunk_max=args.repeat_chunk_max,
                message_body=body,
                request_timeout_sec=args.http_timeout_sec,
            )
            elapsed = time.perf_counter() - t0
            cumulative += accepted
            logger.info(
                "batch %s submit done accepted=%s cumulative=%s elapsed_sec=%.2f",
                i,
                accepted,
                cumulative,
                elapsed,
            )
            if accepted != batch:
                raise SystemExit(f"batch {i}: expected {batch} accepted, got {accepted}")

            if args.in_memory_s3:
                wait_for_pending_zero_via_persistence(
                    client,
                    persistence_base=args.persistence_base,
                    poll_sec=args.drain_poll_sec,
                    timeout_sec=args.drain_timeout_sec,
                    request_timeout_sec=args.http_timeout_sec,
                )
                post_flush_to_disk(
                    client,
                    args.persistence_base,
                    root_override=args.flush_root,
                    request_timeout_sec=args.http_timeout_sec,
                )
            else:
                wait_for_pending_zero(
                    root,
                    poll_sec=args.drain_poll_sec,
                    timeout_sec=args.drain_timeout_sec,
                )

            integrity = post_integrity_check(
                client,
                health_base=args.health_monitor_base,
                token=args.integrity_token,
                timeout_sec=args.integrity_timeout_sec,
            )
            assert_integrity_ok(integrity)
            logger.info(
                "integrity ok summary=%s",
                integrity.get("summary", {}),
            )

            counts = scan_local_s3(root)
            validate_disk_invariants(
                root=root,
                cumulative_messages=cumulative,
                counts=counts,
                baseline=baseline,
            )
            logger.info(
                "disk ok success=%s failed=%s pending=%s notifications=%s",
                counts.success,
                counts.failed,
                counts.pending,
                counts.notifications,
            )

    logger.info("all batches passed cumulative_messages=%s", cumulative)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.error("interrupted")
        raise SystemExit(130) from None
