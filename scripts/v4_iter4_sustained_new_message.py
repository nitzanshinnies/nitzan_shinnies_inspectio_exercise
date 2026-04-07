#!/usr/bin/env python3
"""Sustained ``POST /messages`` against Iter4 DynamoDB + S3 WAL API (async).

Run **in-cluster** with ``--api-base`` (e.g. ``http://inspectio-v3-iter4-api:8000``).
Each request uses a unique ``messageId`` (one DDB put + immediate send attempt + WAL events).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
import uuid

import httpx


def _is_transient_load_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TransportError, httpx.HTTPStatusError)):
        return True
    if isinstance(exc, RuntimeError) and "client has been closed" in str(exc).lower():
        return True
    return False


async def _sender(
    client: httpx.AsyncClient,
    base: str,
    stop_at: float,
) -> tuple[int, int]:
    """Return (accepted_new_messages, transient_errors)."""
    accepted = 0
    transient_errors = 0
    while time.monotonic() < stop_at:
        try:
            r = await client.post(
                f"{base}/messages",
                json={
                    "messageId": str(uuid.uuid4()),
                    "payload": {},
                },
            )
            r.raise_for_status()
            data = r.json()
            if data.get("accepted") is True:
                accepted += 1
        except Exception as exc:  # noqa: BLE001
            if not _is_transient_load_error(exc):
                raise
            transient_errors += 1
            await asyncio.sleep(0.01)
    return accepted, transient_errors


async def _run(args: argparse.Namespace) -> None:
    base = args.api_base.rstrip("/")
    stop_at = time.monotonic() + float(args.duration_sec)
    conc = max(1, int(args.concurrency))
    limits = httpx.Limits(
        max_connections=max(conc + 8, 32),
        max_keepalive_connections=max(conc + 8, 32),
    )
    timeout = httpx.Timeout(120.0)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        r = await client.get(f"{base}/health", timeout=30.0)
        r.raise_for_status()
        tasks = [
            asyncio.create_task(_sender(client, base, stop_at))
            for _ in range(int(args.concurrency))
        ]
        totals = await asyncio.gather(*tasks)
    total = sum(a for a, _ in totals)
    transient_errors = sum(e for _, e in totals)
    dur = float(args.duration_sec)
    print(
        "ITER4_WAL_SUSTAIN_SUMMARY "
        f"accepted_total={total} duration_sec={dur} "
        f"offered_new_message_rps={total / dur:.2f} "
        f"concurrency={args.concurrency} transient_errors={transient_errors}",
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Sustained Iter4 newMessage load")
    p.add_argument(
        "--api-base",
        default=os.environ.get(
            "INSPECTIO_ITER4_LOAD_TEST_API_BASE",
            "http://127.0.0.1:8000",
        ),
    )
    p.add_argument("--duration-sec", type=float, default=60.0)
    p.add_argument("--concurrency", type=int, default=40)
    args = p.parse_args()
    asyncio.run(_run(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
