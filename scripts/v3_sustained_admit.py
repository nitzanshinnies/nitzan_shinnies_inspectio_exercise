#!/usr/bin/env python3
"""Sustained ``POST /messages/repeat`` load (async) to keep the v3 pipeline fed.

Run **in-cluster** (Job) with ``INSPECTIO_LOAD_TEST_API_BASE`` pointing at L1.
Tune ``--concurrency`` × ``--batch`` and ``--duration-sec`` for offered admit rate.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time

import httpx


async def _sender(
    client: httpx.AsyncClient,
    base: str,
    body: str,
    batch: int,
    stop_at: float,
) -> int:
    admitted = 0
    while time.monotonic() < stop_at:
        r = await client.post(
            f"{base}/messages/repeat",
            params={"count": batch},
            json={"body": body},
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
        got = data.get("accepted")
        if got is None:
            raise RuntimeError(f"bad repeat response: {data!r}")
        admitted += int(got)
    return admitted


async def _run(args: argparse.Namespace) -> None:
    base = args.api_base.rstrip("/")
    stop_at = time.monotonic() + float(args.duration_sec)
    body = f"{args.body_prefix}-{time.time_ns()}"
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{base}/healthz", timeout=30.0)
        r.raise_for_status()
        tasks = [
            asyncio.create_task(
                _sender(client, base, body, int(args.batch), stop_at),
            )
            for _ in range(int(args.concurrency))
        ]
        totals = await asyncio.gather(*tasks)
    total = sum(totals)
    dur = float(args.duration_sec)
    print(
        f"SUSTAIN_SUMMARY admitted_total={total} duration_sec={dur} "
        f"offered_admit_rps={total / dur:.2f} concurrency={args.concurrency} "
        f"batch={args.batch}",
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Sustained v3 repeat admission load")
    p.add_argument(
        "--api-base",
        default=os.environ.get(
            "INSPECTIO_LOAD_TEST_API_BASE", "http://inspectio-l1:8080"
        ),
    )
    p.add_argument("--duration-sec", type=float, default=45.0)
    p.add_argument("--concurrency", type=int, default=120)
    p.add_argument("--batch", type=int, default=80)
    p.add_argument("--body-prefix", default="sustain")
    args = p.parse_args()
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
