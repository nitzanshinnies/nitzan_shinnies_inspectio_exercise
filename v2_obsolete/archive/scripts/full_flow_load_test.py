#!/usr/bin/env python3
"""In-VPC load driver for greenfield Inspectio .

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DEFAULT_CHUNK_MAX = 500
DEFAULT_K8S_API = "http://inspectio-api:8000"
DEFAULT_HTTP_TIMEOUT = 120.0
DEFAULT_MAX_TOTAL_SEC = 60.0
DEFAULT_OUTCOME_LIMIT = 10_000
DEFAULT_POLL_SEC = 2.0
DEFAULT_OUTCOME_TIMEOUT = 60.0


class TotalBudgetExceeded(RuntimeError):
    """Raised when wall-clock time exceeds ``--max-total-sec``."""


def _check_run_end(run_end: float | None) -> None:
    if run_end is None:
        return
    if time.monotonic() >= run_end:
        raise TotalBudgetExceeded(
            "load test exceeded --max-total-sec wall clock budget"
        )


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
    *,
    run_end: float | None,
) -> tuple[list[str], list[float]]:
    """Return (all message_ids, chunk_duration_seconds_list)."""
    if total < 1:
        return [], []
    ids: list[str] = []
    durs: list[float] = []
    remaining = total
    base = api_base.rstrip("/")
    while remaining > 0:
        if run_end is not None:
            _check_run_end(run_end)
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


def _split_parallel_counts(total: int, parallel: int) -> list[int]:
    """Split ``total`` into ``parallel`` positive counts (for concurrent HTTP admits)."""
    if parallel < 1:
        parallel = 1
    if parallel == 1:
        return [total]
    parallel = min(parallel, total)
    base = total // parallel
    rem = total % parallel
    return [base + (1 if i < rem else 0) for i in range(parallel)]


def _submit_parallel_admission(
    api_base: str,
    total: int,
    chunk_max: int,
    body: str,
    timeout: float,
    *,
    parallel: int,
    run_end: float | None,
) -> tuple[list[str], list[float], float]:
    """Concurrent ``POST /messages/repeat`` from multiple threads (aggregate N1 driver).

    Returns ``(all_ids, merged_chunk_durs, wall_sec)``. One ``httpx.Client`` per thread.
    """
    counts = _split_parallel_counts(total, parallel)
    if len(counts) == 1:
        with httpx.Client() as client:
            t0 = time.perf_counter()
            ids, durs = _submit_batches(
                client,
                api_base,
                total,
                chunk_max=min(chunk_max, total),
                body=body,
                timeout=timeout,
                run_end=run_end,
            )
            return ids, durs, time.perf_counter() - t0

    def _one(count: int) -> tuple[list[str], list[float]]:
        with httpx.Client() as client:
            return _submit_batches(
                client,
                api_base,
                count,
                chunk_max=min(chunk_max, count),
                body=body,
                timeout=timeout,
                run_end=run_end,
            )

    wall0 = time.perf_counter()
    merged_ids: list[str] = []
    merged_durs: list[float] = []
    with ThreadPoolExecutor(max_workers=len(counts)) as pool:
        futures = [pool.submit(_one, c) for c in counts]
        for fut in as_completed(futures):
            ids, durs = fut.result()
            merged_ids.extend(ids)
            merged_durs.extend(durs)
    wall = time.perf_counter() - wall0
    return merged_ids, merged_durs, wall


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
    run_end: float | None,
    http_timeout: float,
) -> tuple[set[str], float, bool]:
    """Poll success+failed lists until all ``needed`` ids seen.

    Returns (seen, elapsed_sec, timed_out). ``timed_out`` is True when the loop
    exited because ``deadline_monotonic`` or ``run_end`` was reached before
    every id appeared.
    """
    t0 = time.perf_counter()
    seen: set[str] = set()

    def _loop_deadline() -> float:
        ends = [deadline_monotonic]
        if run_end is not None:
            ends.append(run_end)
        return min(ends)

    while time.perf_counter() < _loop_deadline():
        for path in ("/messages/success", "/messages/failed"):
            items = _fetch_outcomes(client, api_base, path, limit, http_timeout)
            for it in items:
                mid = it.get("messageId")
                if isinstance(mid, str) and mid in needed:
                    seen.add(mid)
        if needed <= seen:
            return seen, time.perf_counter() - t0, False
        if run_end is not None:
            _check_run_end(run_end)
        time.sleep(poll_sec)
    return seen, time.perf_counter() - t0, True


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
    p.add_argument(
        "--http-timeout-sec",
        type=float,
        default=float(
            os.environ.get(
                "INSPECTIO_LOAD_TEST_HTTP_TIMEOUT_SEC", str(DEFAULT_HTTP_TIMEOUT)
            )
        ),
    )
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
        help=(
            "Max seconds to poll for terminals after the last message is admitted "
            "(default: 60). Exceeding this fails the run."
        ),
    )
    p.add_argument(
        "--max-total-sec",
        type=float,
        default=float(
            os.environ.get("INSPECTIO_LOAD_TEST_MAX_TOTAL_SEC", DEFAULT_MAX_TOTAL_SEC)
        ),
        help=(
            "Wall-clock cap from process start (default: 60). "
            "Use 0 to disable (long N1 admit benches; rely on Kubernetes "
            "activeDeadlineSeconds + kubectl wait instead). "
            "When >0, align Job activeDeadlineSeconds and kubectl wait above this value."
        ),
    )
    p.add_argument(
        "--json-summary",
        action="store_true",
        help="Print one JSON object with metrics to stdout",
    )
    p.add_argument(
        "--parallel-admission",
        type=int,
        default=int(os.environ.get("INSPECTIO_LOAD_TEST_PARALLEL_ADMISSION", "1")),
        help=(
            "Concurrent HTTP clients issuing /messages/repeat (default: 1). "
            "Use >1 to measure aggregate admit RPS across Service load-balanced API pods (N1)."
        ),
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
    max_total = float(args.max_total_sec)
    run_end: float | None
    if max_total <= 0:
        run_end = None
        log.info("max-total-sec disabled (no driver wall clock cap)")
    else:
        run_end = time.monotonic() + max_total

    summaries: list[dict[str, Any]] = []

    try:
        with httpx.Client() as client:
            _check_run_end(run_end)
            r = client.get(f"{api_base.rstrip('/')}/healthz", timeout=timeout)
            r.raise_for_status()
            log.info("healthz ok from %s", api_base)

            for n in sizes:
                _check_run_end(run_end)
                par = max(1, int(args.parallel_admission))
                log.info(
                    "phase size=%s admission start (parallel_admission=%s)",
                    n,
                    par,
                )
                if par > 1:
                    ids, chunk_durs, admission_sec = _submit_parallel_admission(
                        api_base,
                        n,
                        chunk_max=args.chunk_max,
                        body=args.body,
                        timeout=timeout,
                        parallel=par,
                        run_end=run_end,
                    )
                else:
                    t0 = time.perf_counter()
                    ids, chunk_durs = _submit_batches(
                        client,
                        api_base,
                        n,
                        chunk_max=min(args.chunk_max, n),
                        body=args.body,
                        timeout=timeout,
                        run_end=run_end,
                    )
                    admission_sec = time.perf_counter() - t0
                chunk_ms = sorted(d * 1000.0 for d in chunk_durs)
                needed = set(ids)

                phase: dict[str, Any] = {
                    "size": n,
                    "max_total_sec_cap": None
                    if run_end is None
                    else round(max_total, 3),
                    "parallel_admission": par,
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
                    outcome_budget = float(args.outcome_timeout_sec)
                    deadline = time.monotonic() + outcome_budget
                    seen, drain_sec, timed_out = _wait_all_terminals(
                        client,
                        api_base,
                        needed,
                        limit=min(args.outcome_limit, max(n, 1)),
                        poll_sec=float(args.outcome_poll_sec),
                        deadline_monotonic=deadline,
                        run_end=run_end,
                        http_timeout=timeout,
                    )
                    phase["drain_sec"] = round(drain_sec, 3)
                    phase["outcome_wait_budget_sec"] = round(outcome_budget, 3)
                    phase["terminals_seen"] = len(seen)
                    phase["drain_complete"] = needed <= seen
                    if not phase["drain_complete"]:
                        phase["outcome_wait_timed_out"] = timed_out
                        if run_end is not None and time.monotonic() >= run_end:
                            log.error(
                                "hard fail: exceeded --max-total-sec wall clock "
                                "(need=%s terminals, saw %s)",
                                len(needed),
                                len(seen & needed),
                            )
                        else:
                            log.error(
                                "hard fail: outcome wait exceeded %.3fs after messages were sent "
                                "(need=%s terminals, saw %s in window)",
                                outcome_budget,
                                len(needed),
                                len(seen & needed),
                            )
                        if args.json_summary:
                            summaries.append(phase)
                            print(
                                json.dumps({"ok": False, "phases": summaries}, indent=2)
                            )
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
    except TotalBudgetExceeded as e:
        log.error("%s", e)
        if args.json_summary:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "max_total_sec_exceeded",
                        "phases": summaries,
                    },
                    indent=2,
                )
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
