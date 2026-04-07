#!/usr/bin/env python3
"""Single HTTP ``POST /messages/repeat`` admission benchmark (no sustained concurrency).

Use this to measure **one large bulk admit** (one batch id, one shard) end-to-end for
the POST handler and downstream enqueue/persist path — not offered RPS under many
parallel clients (see ``scripts/v3_sustained_admit.py``).

Run in-cluster with ``INSPECTIO_LOAD_TEST_API_BASE`` (L1) per P7/P12.9 conventions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx

from inspectio.v3.load_harness.repeat_limits import validated_repeat_count
from inspectio.v3.load_harness.stats import admission_rps

DEFAULT_API_BASE_K8S = "http://inspectio-l1:8080"
DEFAULT_BODY_PREFIX = "single-bulk"
DEFAULT_COUNT = 10_000
DEFAULT_HTTP_TIMEOUT_SEC = 600.0


def _healthz(client: httpx.Client, api_base: str, timeout: float) -> None:
    base = api_base.rstrip("/")
    r = client.get(f"{base}/healthz", timeout=timeout)
    r.raise_for_status()


def _post_one_repeat(
    client: httpx.Client,
    api_base: str,
    count: int,
    body: str,
    timeout: float,
    idempotency_key: str | None,
) -> tuple[float, dict[str, Any]]:
    base = api_base.rstrip("/")
    headers: dict[str, str] = {}
    if idempotency_key is not None and idempotency_key.strip() != "":
        headers["Idempotency-Key"] = idempotency_key.strip()
    t0 = time.perf_counter()
    r = client.post(
        f"{base}/messages/repeat",
        params={"count": count},
        json={"body": body},
        timeout=timeout,
        headers=headers or None,
    )
    elapsed_sec = time.perf_counter() - t0
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        msg = f"unexpected repeat response: {data!r}"
        raise RuntimeError(msg)
    accepted = data.get("accepted")
    if accepted != count:
        msg = f"unexpected accepted count: {data!r}"
        raise RuntimeError(msg)
    return elapsed_sec, data


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Single POST /messages/repeat bulk admit benchmark",
    )
    p.add_argument(
        "--kubernetes",
        action="store_true",
        help=f"Use default API base {DEFAULT_API_BASE_K8S!r} when --api-base unset",
    )
    p.add_argument(
        "--api-base",
        default=os.environ.get("INSPECTIO_LOAD_TEST_API_BASE", "").strip(),
        help="L1 or L2 base URL (trailing slash optional)",
    )
    p.add_argument(
        "--count",
        type=int,
        default=int(
            os.environ.get(
                "INSPECTIO_SINGLE_BULK_COUNT",
                str(DEFAULT_COUNT),
            ),
        ),
        help="Repeat count for the single request (one batch)",
    )
    p.add_argument(
        "--body-prefix",
        default=os.environ.get(
            "INSPECTIO_SINGLE_BULK_BODY_PREFIX",
            DEFAULT_BODY_PREFIX,
        ),
        help="Body string prefix (unique suffix added per run)",
    )
    p.add_argument(
        "--http-timeout-sec",
        type=float,
        default=float(
            os.environ.get(
                "INSPECTIO_LOAD_TEST_HTTP_TIMEOUT_SEC",
                str(DEFAULT_HTTP_TIMEOUT_SEC),
            ),
        ),
    )
    p.add_argument(
        "--idempotency-key",
        default=os.environ.get("INSPECTIO_SINGLE_BULK_IDEMPOTENCY_KEY", "").strip()
        or None,
        help="Optional Idempotency-Key header (re-submit same logical bulk)",
    )
    p.add_argument(
        "--skip-healthz",
        action="store_true",
        help="Do not GET /healthz before the repeat POST",
    )
    p.add_argument(
        "--json-summary",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Emit JSON to stdout (default on)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    api_base = (args.api_base or "").strip()
    if args.kubernetes and not api_base:
        api_base = os.environ.get(
            "INSPECTIO_LOAD_TEST_API_BASE",
            DEFAULT_API_BASE_K8S,
        ).strip()
    if not api_base:
        api_base = "http://127.0.0.1:8080"

    try:
        count = validated_repeat_count(int(args.count))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    timeout = float(args.http_timeout_sec)
    body = f"{args.body_prefix}-{time.time_ns()}"

    try:
        with httpx.Client() as client:
            if not args.skip_healthz:
                _healthz(client, api_base, min(timeout, 60.0))
            admit_sec, payload = _post_one_repeat(
                client,
                api_base,
                count,
                body,
                timeout,
                args.idempotency_key,
            )
    except Exception as exc:  # noqa: BLE001
        err = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        print(json.dumps(err, indent=2 if args.json_summary else None))
        return 1

    rps = admission_rps(count, admit_sec)
    batch_id = payload.get("batchCorrelationId")
    line = (
        f"SINGLE_BULK_SUMMARY count={count} admit_sec={admit_sec:.6f} "
        f"admission_rps={rps:.2f} batch_correlation_id={batch_id!r}"
    )
    print(line)
    if args.json_summary:
        summary: dict[str, Any] = {
            "ok": True,
            "api_base": api_base,
            "recipients_admitted": count,
            "admit_sec": round(admit_sec, 6),
            "admission_rps": round(rps, 2),
            "batch_correlation_id": batch_id,
            "repeat_response": payload,
        }
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
