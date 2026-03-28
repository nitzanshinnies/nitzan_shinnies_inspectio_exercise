#!/usr/bin/env python3
"""In-VPC load driver for greenfield Inspectio (§28.6, P10).

Primary metrics (valid **AWS throughput claims** only when run **inside** the
cluster/VPC—see workspace rules):

- **Admission:** ``POST /messages/repeat`` chunk timings → RPS and latency percentiles.
- **Drain (optional):** poll ``GET /messages/success`` and ``/messages/failed`` until
  all submitted ``messageId`` values appear (requires
  ``INSPECTIO_OUTCOMES_MAX_LIMIT`` ≥ batch size on API/notification).

**Do not** use ``kubectl port-forward`` from a laptop as proof of production
throughput; use a Kubernetes **Job** (see ``deploy/kubernetes/load-test-job.yaml``
and ``deploy/kubernetes/README.md``).

Examples::

    # In-cluster (default API host)
    python scripts/full_flow_load_test.py --kubernetes --sizes 1000 --wait-outcomes

    # Laptop against local compose (smoke only, not AWS SLO evidence)
    python scripts/full_flow_load_test.py \\
        --api-base http://127.0.0.1:8000 --sizes 100 --no-wait-outcomes
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from typing import Any

import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DEFAULT_CHUNK_MAX = 500
DEFAULT_K8S_API = "http://inspectio-api:8000"
DEFAULT_HTTP_TIMEOUT = 120.0
DEFAULT_OUTCOME_LIMIT = 10_000
DEFAULT_POLL_SEC = 2.0
DEFAULT_OUTCOME_TIMEOUT = 7200.0


def _percentile_sorted(sorted_ms: list[float], p: float) -> float:
    if not sorted_ms:
        return 0.0
    k = max(0, min(len(sorted_ms) - 1, int(round((p / 100.0) * (len(sorted_ms) - 1)))))
    return sorted_ms[k]


def _parse_sizes(raw: str) -> tuple[int, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise SystemExit("need at least one --sizes value")
    return tuple(int(p, 10) for p in parts)


def _submit_batches(
    client: httpx.Client,
    api_base: str,
    total: int,
    chunk_max: int,
    body: str,
    timeout: float,
) -> tuple[list[str], list[float]]:
    """Return (all message_ids, chunk_duration_seconds_list)."""
    if total < 1:
        return [], []
    ids: list[str] = []
    durs: list[float] = []
    remaining = total
    base = api_base.rstrip("/")
    while remaining > 0:
        chunk = min(chunk_max, remaining)
        t0 = time.perf_counter()
        r = client.post(
            f"{base}/messages/repeat",
            params={"count": chunk},
            json={"body": body},
            timeout=timeout,
        )
        durs.append(time.perf_counter() - t0)
        r.raise_for_status()
        data = r.json()
        mids = data.get("messageIds")
        if not isinstance(mids, list) or len(mids) != chunk:
            raise RuntimeError(f"unexpected response shape: {data!r}")
        ids.extend(str(x) for x in mids)
        remaining -= chunk
    return ids, durs


def _fetch_outcomes(
    client: httpx.Client,
    api_base: str,
    path: str,
    limit: int,
    timeout: float,
) -> list[dict[str, Any]]:
    base = api_base.rstrip("/")
    r = client.get(
        f"{base}{path}",
        params={"limit": limit},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    items = data.get("items")
    if not isinstance(items, list):
        raise RuntimeError(f"bad outcome json: {data!r}")
    return items


def _wait_all_terminals(
    client: httpx.Client,
    api_base: str,
    needed: set[str],
    *,
    limit: int,
    poll_sec: float,
    deadline_monotonic: float,
    http_timeout: float,
) -> tuple[set[str], float]:
    """Poll success+failed lists until all ``needed`` ids seen. Returns (seen, elapsed_sec)."""
    t0 = time.perf_counter()
    seen: set[str] = set()
    while time.perf_counter() < deadline_monotonic:
        for path in ("/messages/success", "/messages/failed"):
            items = _fetch_outcomes(client, api_base, path, limit, http_timeout)
            for it in items:
                mid = it.get("messageId")
                if isinstance(mid, str) and mid in needed:
                    seen.add(mid)
        if needed <= seen:
            return seen, time.perf_counter() - t0
        time.sleep(poll_sec)
    return seen, time.perf_counter() - t0


def main() -> int:
    p = argparse.ArgumentParser(description="Greenfield Inspectio load test driver")
    p.add_argument(
        "--kubernetes",
        action="store_true",
        help=f"Use in-cluster default API base ({DEFAULT_K8S_API})",
    )
    p.add_argument(
        "--api-base",
        default=os.environ.get("INSPECTIO_LOAD_TEST_API_BASE", ""),
        help="Override API base URL",
    )
    p.add_argument(
        "--sizes",
        default=os.environ.get("INSPECTIO_LOAD_TEST_SIZES", "1000"),
        help="Comma-separated batch sizes (messages per phase)",
    )
    p.add_argument(
        "--chunk-max",
        type=int,
        default=int(os.environ.get("INSPECTIO_LOAD_TEST_CHUNK_MAX", DEFAULT_CHUNK_MAX)),
    )
    p.add_argument("--body", default="load-test body")
    p.add_argument("--http-timeout-sec", type=float, default=DEFAULT_HTTP_TIMEOUT)
    p.add_argument(
        "--wait-outcomes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Poll GET outcomes until all submitted ids appear",
    )
    p.add_argument("--outcome-limit", type=int, default=DEFAULT_OUTCOME_LIMIT)
    p.add_argument("--outcome-poll-sec", type=float, default=DEFAULT_POLL_SEC)
    p.add_argument(
        "--outcome-timeout-sec",
        type=float,
        default=DEFAULT_OUTCOME_TIMEOUT,
    )
    p.add_argument(
        "--json-summary",
        action="store_true",
        help="Print one JSON object with metrics to stdout",
    )
    args = p.parse_args()

    api_base = (args.api_base or "").strip()
    if args.kubernetes and not api_base:
        api_base = os.environ.get(
            "INSPECTIO_LOAD_TEST_API_BASE", DEFAULT_K8S_API
        ).strip()
    if not api_base:
        api_base = "http://127.0.0.1:8000"

    sizes = _parse_sizes(args.sizes)
    timeout = float(args.http_timeout_sec)

    summaries: list[dict[str, Any]] = []

    with httpx.Client() as client:
        r = client.get(f"{api_base.rstrip('/')}/healthz", timeout=timeout)
        r.raise_for_status()
        log.info("healthz ok from %s", api_base)

        for n in sizes:
            log.info("phase size=%s admission start", n)
            t0 = time.perf_counter()
            ids, chunk_durs = _submit_batches(
                client,
                api_base,
                n,
                chunk_max=min(args.chunk_max, n),
                body=args.body,
                timeout=timeout,
            )
            admission_sec = time.perf_counter() - t0
            chunk_ms = sorted(d * 1000.0 for d in chunk_durs)
            needed = set(ids)

            phase: dict[str, Any] = {
                "size": n,
                "admission_sec": round(admission_sec, 3),
                "admission_rps": round(n / admission_sec, 2)
                if admission_sec > 0
                else 0.0,
                "chunks": len(chunk_durs),
            }
            if chunk_ms:
                phase["chunk_latency_ms_p50"] = round(
                    _percentile_sorted(chunk_ms, 50), 2
                )
                phase["chunk_latency_ms_p95"] = round(
                    _percentile_sorted(chunk_ms, 95), 2
                )
                phase["chunk_latency_ms_p99"] = round(
                    _percentile_sorted(chunk_ms, 99), 2
                )

            if args.wait_outcomes:
                if n > args.outcome_limit:
                    log.warning(
                        "size %s > outcome-limit %s; drain may never complete. "
                        "Raise INSPECTIO_OUTCOMES_MAX_LIMIT on API/notification or lower size.",
                        n,
                        args.outcome_limit,
                    )
                deadline = time.monotonic() + float(args.outcome_timeout_sec)
                seen, drain_sec = _wait_all_terminals(
                    client,
                    api_base,
                    needed,
                    limit=min(args.outcome_limit, max(n, 1)),
                    poll_sec=float(args.outcome_poll_sec),
                    deadline_monotonic=deadline,
                    http_timeout=timeout,
                )
                phase["drain_sec"] = round(drain_sec, 3)
                phase["terminals_seen"] = len(seen)
                phase["drain_complete"] = needed <= seen
                if not phase["drain_complete"]:
                    log.error(
                        "drain incomplete: need=%s seen=%s",
                        len(needed),
                        len(seen & needed),
                    )
                    if args.json_summary:
                        summaries.append(phase)
                        print(json.dumps({"ok": False, "phases": summaries}, indent=2))
                    return 1
                e2e = admission_sec + drain_sec
                phase["e2e_sec"] = round(e2e, 3)
                phase["e2e_rps"] = round(n / e2e, 2) if e2e > 0 else 0.0
                log.info(
                    "phase size=%s admission_rps=%s e2e_rps=%s drain_sec=%s",
                    n,
                    phase["admission_rps"],
                    phase.get("e2e_rps"),
                    phase.get("drain_sec"),
                )
            else:
                log.info(
                    "phase size=%s admission_rps=%s (no outcome wait)",
                    n,
                    phase["admission_rps"],
                )

            summaries.append(phase)

    out = {"ok": True, "api_base": api_base, "phases": summaries}
    if args.json_summary:
        print(json.dumps(out, indent=2))
    else:
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
