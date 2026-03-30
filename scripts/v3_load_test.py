#!/usr/bin/env python3
"""v3 in-cluster load driver (P7).

**AWS / EKS throughput claims** only when this runs **inside** the cluster (Job or
Pod) hitting in-cluster Service URLs — not via laptop ``kubectl port-forward``.

v3 ``POST /messages/repeat`` returns a **summary** (no per-``messageId`` list).
Optional ``--wait-successes`` polls ``GET /messages/success`` until at least
``min(expected_recipients, limit)`` items appear (``limit`` ≤ 100). For
``expected_recipients > 100`` the outcomes API **cannot** prove all terminals;
use worker logs / metrics (e.g. ``send_ok``) for full **3.1** send-side counts
— see ``deploy/kubernetes/README.md`` (P7).
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

from inspectio.v3.load_harness.stats import (
    admission_rps,
    outcomes_visible_target,
    parse_positive_int_csv,
    percentile_sorted,
    split_parallel_counts,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

DEFAULT_CHUNK_MAX = 500
# Through L1 (P5); override with INSPECTIO_LOAD_TEST_API_BASE for direct L2.
DEFAULT_K8S_API_BASE = "http://inspectio-l1:8080"
DEFAULT_HTTP_TIMEOUT = 120.0
DEFAULT_MAX_TOTAL_SEC = 60.0
DEFAULT_OUTCOME_POLL_SEC = 0.5
DEFAULT_OUTCOME_TIMEOUT_SEC = 55.0
DEFAULT_SUCCESS_LIMIT = 100


class TotalBudgetExceeded(RuntimeError):
    """Wall clock exceeded ``--max-total-sec``."""


def _check_run_end(run_end: float | None) -> None:
    if run_end is None:
        return
    if time.monotonic() >= run_end:
        raise TotalBudgetExceeded(
            "load test exceeded --max-total-sec wall clock budget",
        )


def _submit_repeat_chunks(
    client: httpx.Client,
    api_base: str,
    total: int,
    chunk_max: int,
    body: str,
    timeout: float,
    *,
    run_end: float | None,
) -> tuple[list[float], int]:
    """Return (per-chunk durations in seconds, total recipients admitted)."""
    if total < 1:
        return [], 0
    durs: list[float] = []
    remaining = total
    base = api_base.rstrip("/")
    admitted = 0
    while remaining > 0:
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
        accepted = data.get("accepted")
        if accepted != chunk:
            raise RuntimeError(f"unexpected repeat response: {data!r}")
        admitted += chunk
        remaining -= chunk
    return durs, admitted


def _submit_parallel_repeat(
    api_base: str,
    total: int,
    chunk_max: int,
    body: str,
    timeout: float,
    *,
    parallel: int,
    run_end: float | None,
) -> tuple[list[float], int, float]:
    counts = split_parallel_counts(total, parallel)
    if len(counts) == 1:
        with httpx.Client() as client:
            t0 = time.perf_counter()
            durs, admitted = _submit_repeat_chunks(
                client,
                api_base,
                total,
                chunk_max=min(chunk_max, total),
                body=body,
                timeout=timeout,
                run_end=run_end,
            )
            return durs, admitted, time.perf_counter() - t0

    def _one(count: int) -> tuple[list[float], int]:
        with httpx.Client() as client:
            return _submit_repeat_chunks(
                client,
                api_base,
                count,
                chunk_max=min(chunk_max, count),
                body=body,
                timeout=timeout,
                run_end=run_end,
            )

    wall0 = time.perf_counter()
    merged_durs: list[float] = []
    admitted_total = 0
    with ThreadPoolExecutor(max_workers=len(counts)) as pool:
        futures = [pool.submit(_one, c) for c in counts]
        for fut in as_completed(futures):
            durs, adm = fut.result()
            merged_durs.extend(durs)
            admitted_total += adm
    return merged_durs, admitted_total, time.perf_counter() - wall0


def _fetch_success_items(
    client: httpx.Client,
    api_base: str,
    limit: int,
    timeout: float,
) -> list[dict[str, Any]]:
    base = api_base.rstrip("/")
    r = client.get(
        f"{base}/messages/success",
        params={"limit": limit},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    items = data.get("items")
    if not isinstance(items, list):
        raise RuntimeError(f"bad success json: {data!r}")
    return items


def _wait_success_visible(
    client: httpx.Client,
    api_base: str,
    *,
    needed_visible: int,
    limit: int,
    poll_sec: float,
    deadline_monotonic: float,
    run_end: float | None,
    http_timeout: float,
) -> tuple[int, float, bool]:
    """Poll until len(items) >= needed_visible or timeout."""
    t0 = time.perf_counter()
    while True:
        now = time.monotonic()
        if now >= deadline_monotonic:
            items = _fetch_success_items(client, api_base, limit, http_timeout)
            return len(items), time.perf_counter() - t0, True
        if run_end is not None and now >= run_end:
            items = _fetch_success_items(client, api_base, limit, http_timeout)
            return len(items), time.perf_counter() - t0, True
        items = _fetch_success_items(client, api_base, limit, http_timeout)
        if len(items) >= needed_visible:
            return len(items), time.perf_counter() - t0, False
        _check_run_end(run_end)
        time.sleep(poll_sec)


def main() -> int:
    p = argparse.ArgumentParser(description="Inspectio v3 in-cluster load driver")
    p.add_argument(
        "--kubernetes",
        action="store_true",
        help=f"Default API base from env or {DEFAULT_K8S_API_BASE!r} (in-cluster L1)",
    )
    p.add_argument(
        "--api-base",
        default=os.environ.get("INSPECTIO_LOAD_TEST_API_BASE", ""),
        help="HTTP base for L1 or L2 (trailing slash optional)",
    )
    p.add_argument(
        "--sizes",
        default=os.environ.get("INSPECTIO_LOAD_TEST_SIZES", "10"),
        help="Comma-separated recipient counts per phase",
    )
    p.add_argument(
        "--chunk-max",
        type=int,
        default=int(os.environ.get("INSPECTIO_LOAD_TEST_CHUNK_MAX", DEFAULT_CHUNK_MAX)),
    )
    p.add_argument("--body", default="v3-load-test")
    p.add_argument(
        "--http-timeout-sec",
        type=float,
        default=float(
            os.environ.get(
                "INSPECTIO_LOAD_TEST_HTTP_TIMEOUT_SEC",
                str(DEFAULT_HTTP_TIMEOUT),
            ),
        ),
    )
    p.add_argument(
        "--wait-successes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Poll GET /messages/success until min(N, limit) rows (best-effort)",
    )
    p.add_argument(
        "--success-limit",
        type=int,
        default=int(
            os.environ.get(
                "INSPECTIO_LOAD_TEST_SUCCESS_LIMIT",
                str(DEFAULT_SUCCESS_LIMIT),
            ),
        ),
    )
    p.add_argument(
        "--outcome-poll-sec",
        type=float,
        default=float(
            os.environ.get(
                "INSPECTIO_LOAD_TEST_OUTCOME_POLL_SEC",
                str(DEFAULT_OUTCOME_POLL_SEC),
            ),
        ),
    )
    p.add_argument(
        "--outcome-timeout-sec",
        type=float,
        default=float(
            os.environ.get(
                "INSPECTIO_LOAD_TEST_OUTCOME_TIMEOUT_SEC",
                str(DEFAULT_OUTCOME_TIMEOUT_SEC),
            ),
        ),
    )
    p.add_argument(
        "--max-total-sec",
        type=float,
        default=float(
            os.environ.get(
                "INSPECTIO_LOAD_TEST_MAX_TOTAL_SEC",
                str(DEFAULT_MAX_TOTAL_SEC),
            ),
        ),
        help=(
            "Wall-clock cap from process start (default 60). "
            "Use 0 to disable; align Kubernetes activeDeadlineSeconds + kubectl wait."
        ),
    )
    p.add_argument(
        "--parallel-admission",
        type=int,
        default=int(
            os.environ.get("INSPECTIO_LOAD_TEST_PARALLEL_ADMISSION", "1"),
        ),
    )
    p.add_argument(
        "--json-summary",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Emit JSON metrics to stdout (default: on; use --no-json-summary for compact one line)",
    )
    args = p.parse_args()

    api_base = (args.api_base or "").strip()
    if args.kubernetes and not api_base:
        api_base = os.environ.get(
            "INSPECTIO_LOAD_TEST_API_BASE",
            DEFAULT_K8S_API_BASE,
        ).strip()
    if not api_base:
        api_base = "http://127.0.0.1:8080"

    try:
        sizes = parse_positive_int_csv(args.sizes, field_name="--sizes")
    except ValueError as e:
        raise SystemExit(str(e)) from e
    timeout = float(args.http_timeout_sec)
    max_total = float(args.max_total_sec)
    run_end: float | None
    if max_total <= 0:
        run_end = None
        log.info("max-total-sec disabled (no driver wall clock cap)")
    else:
        run_end = time.monotonic() + max_total

    success_limit = max(1, min(int(args.success_limit), 100))
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
                    "phase recipients=%s admission start (parallel=%s)",
                    n,
                    par,
                )
                if par > 1:
                    chunk_durs, admitted, admission_sec = _submit_parallel_repeat(
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
                    chunk_durs, admitted = _submit_repeat_chunks(
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
                phase: dict[str, Any] = {
                    "recipients_admitted": admitted,
                    "max_total_sec_cap": None
                    if run_end is None
                    else round(max_total, 3),
                    "parallel_admission": par,
                    "admission_sec": round(admission_sec, 3),
                    "admission_rps": admission_rps(admitted, admission_sec),
                    "chunks": len(chunk_durs),
                    "completion_detection": "outcomes_get_success_capped",
                }
                if chunk_ms:
                    phase["chunk_latency_ms_p50"] = round(
                        percentile_sorted(chunk_ms, 50),
                        2,
                    )
                    phase["chunk_latency_ms_p95"] = round(
                        percentile_sorted(chunk_ms, 95),
                        2,
                    )
                    phase["chunk_latency_ms_p99"] = round(
                        percentile_sorted(chunk_ms, 99),
                        2,
                    )

                if args.wait_successes:
                    needed = outcomes_visible_target(n, success_limit)
                    if n > success_limit:
                        phase["outcomes_visibility_note"] = (
                            f"recipient_count {n} exceeds success API cap "
                            f"{success_limit}; cannot confirm all via GET only — "
                            "check worker logs/metrics for send_ok (plan 3.1)."
                        )
                    outcome_budget = float(args.outcome_timeout_sec)
                    deadline = time.monotonic() + outcome_budget
                    final_len, drain_sec, timed_out = _wait_success_visible(
                        client,
                        api_base,
                        needed_visible=needed,
                        limit=success_limit,
                        poll_sec=float(args.outcome_poll_sec),
                        deadline_monotonic=deadline,
                        run_end=run_end,
                        http_timeout=timeout,
                    )
                    phase["drain_sec"] = round(drain_sec, 3)
                    phase["outcome_wait_budget_sec"] = round(outcome_budget, 3)
                    phase["success_items_visible"] = final_len
                    phase["success_items_needed_visible"] = needed
                    phase["outcome_wait_timed_out"] = timed_out
                    if timed_out or final_len < needed:
                        log.error(
                            "outcome wait incomplete (need_visible=%s saw=%s timed_out=%s)",
                            needed,
                            final_len,
                            timed_out,
                        )
                        summaries.append(phase)
                        err = {"ok": False, "phases": summaries}
                        print(
                            json.dumps(err, indent=2 if args.json_summary else None),
                        )
                        return 1
                    e2e = admission_sec + drain_sec
                    phase["e2e_sec"] = round(e2e, 3)
                    phase["observed_success_throughput_rps"] = (
                        round(needed / drain_sec, 2) if drain_sec > 0 else 0.0
                    )
                    log.info(
                        "phase n=%s admission_rps=%s observed_success_rps=%s drain_sec=%s",
                        n,
                        phase["admission_rps"],
                        phase.get("observed_success_throughput_rps"),
                        phase.get("drain_sec"),
                    )
                else:
                    log.info(
                        "phase n=%s admission_rps=%s (no success wait)",
                        n,
                        phase["admission_rps"],
                    )

                summaries.append(phase)

        out: dict[str, Any] = {"ok": True, "api_base": api_base, "phases": summaries}
        print(json.dumps(out, indent=2 if args.json_summary else None))
        return 0
    except TotalBudgetExceeded as e:
        log.error("%s", e)
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "max_total_sec_exceeded",
                    "phases": summaries,
                },
                indent=2 if args.json_summary else None,
            ),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
