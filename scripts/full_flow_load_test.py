#!/usr/bin/env python3
"""Phase-10 full-flow load test harness (must run in-cluster for AWS claims)."""

from __future__ import annotations

import argparse
import sys
import time
import uuid

import httpx

DEFAULT_BODY = "phase-10-load-test"
DEFAULT_COUNT = 1000
DEFAULT_FAILED_PATH = "/messages/failed"
DEFAULT_LIMIT = 100
DEFAULT_SUCCESS_PATH = "/messages/success"
DEFAULT_TIMEOUT_SEC = 180
POLL_INTERVAL_SEC = 1.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--timeout-sec", type=int, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument("--success-path", default=DEFAULT_SUCCESS_PATH)
    parser.add_argument("--failed-path", default=DEFAULT_FAILED_PATH)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--kubernetes", action="store_true")
    return parser.parse_args()


def _parse_message_id(response: dict) -> str:
    message_ids = response.get("messageIds")
    if not isinstance(message_ids, list) or not message_ids:
        raise RuntimeError("repeat response missing messageIds")
    candidate = message_ids[0]
    if not isinstance(candidate, str):
        raise RuntimeError("messageIds[0] must be a string")
    return candidate


def _parse_message_ids(response: dict) -> set[str]:
    message_ids = response.get("messageIds")
    if not isinstance(message_ids, list) or not message_ids:
        raise RuntimeError("repeat response missing messageIds")
    parsed: set[str] = set()
    for item in message_ids:
        if not isinstance(item, str):
            raise RuntimeError("messageIds items must be strings")
        parsed.add(item)
    return parsed


def main() -> int:
    args = _parse_args()
    if not args.kubernetes:
        print(
            "Refusing to run without --kubernetes for phase-10 baseline.",
            file=sys.stderr,
        )
        return 2
    if args.count < 1:
        print("--count must be >= 1", file=sys.stderr)
        return 2
    if args.limit < 1:
        print("--limit must be >= 1", file=sys.stderr)
        return 2

    run_id = str(uuid.uuid4())
    body = f"{DEFAULT_BODY}-{run_id}"
    base_url = args.api_base_url.rstrip("/")
    start = time.monotonic()

    with httpx.Client(timeout=10.0) as client:
        t0 = time.monotonic()
        repeat = client.post(
            f"{base_url}/messages/repeat",
            params={"count": args.count},
            json={"body": body},
        )
        repeat.raise_for_status()
        t_post = time.monotonic()
        response_json = repeat.json()
        t_json = time.monotonic()
        first_message_id = _parse_message_id(response_json)
        submitted_ids = _parse_message_ids(response_json)
        print(
            "[inspectio-perf] component=load_test_client phase=POST_messages_repeat "
            f"count={args.count} http_ms={(t_post - t0) * 1000:.3f} "
            f"parse_json_ms={(t_json - t_post) * 1000:.3f}"
        )

        poll_iter = 0
        poll_success_ms = 0.0
        poll_failed_ms = 0.0
        poll_sleep_ms = 0.0
        deadline = time.monotonic() + float(args.timeout_sec)
        while time.monotonic() < deadline:
            s0 = time.monotonic()
            success_resp = client.get(
                f"{base_url}{args.success_path}",
                params={"limit": args.limit},
            )
            s1 = time.monotonic()
            failed_resp = client.get(
                f"{base_url}{args.failed_path}",
                params={"limit": args.limit},
            )
            s2 = time.monotonic()
            success_resp.raise_for_status()
            failed_resp.raise_for_status()
            poll_success_ms += (s1 - s0) * 1000
            poll_failed_ms += (s2 - s1) * 1000
            success_items = success_resp.json().get("items", [])
            failed_items = failed_resp.json().get("items", [])
            observed_ids = {
                str(item.get("messageId"))
                for item in (success_items + failed_items)
                if isinstance(item.get("messageId"), str)
            }
            poll_iter += 1
            if submitted_ids.intersection(observed_ids):
                elapsed = time.monotonic() - start
                print(
                    "[inspectio-perf] component=load_test_client phase=poll_loop "
                    f"iterations={poll_iter} "
                    f"sum_get_success_ms={poll_success_ms:.3f} "
                    f"sum_get_failed_ms={poll_failed_ms:.3f} "
                    f"sum_sleep_ms={poll_sleep_ms:.3f}"
                )
                print(
                    f"phase10_load_ok count={args.count} elapsed_sec={elapsed:.2f} "
                    f"first_message_id={first_message_id}"
                )
                return 0
            sl0 = time.monotonic()
            time.sleep(POLL_INTERVAL_SEC)
            poll_sleep_ms += (time.monotonic() - sl0) * 1000

    print(
        f"Timed out waiting for terminal messageId={first_message_id}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
