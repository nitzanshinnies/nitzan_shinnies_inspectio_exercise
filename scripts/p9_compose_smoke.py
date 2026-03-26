"""P9 compose smoke: POST /messages then verify terminal GET projection."""

from __future__ import annotations

import argparse
import sys
import time

import httpx

DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_LIMIT = 100
DEFAULT_TIMEOUT_SEC = 30
POLL_INTERVAL_SEC = 0.5


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--body", default="p9 smoke message")
    parser.add_argument("--to", default="+10000000000")
    parser.add_argument("--timeout-sec", type=int, default=DEFAULT_TIMEOUT_SEC)
    return parser.parse_args()


def _post_message(api_base: str, body: str, to: str) -> str:
    response = httpx.post(
        f"{api_base}/messages", json={"body": body, "to": to}, timeout=5
    )
    response.raise_for_status()
    payload = response.json()
    return str(payload["messageId"])


def _fetch_terminals(api_base: str) -> list[dict]:
    success = httpx.get(
        f"{api_base}/messages/success",
        params={"limit": DEFAULT_LIMIT},
        timeout=5,
    )
    success.raise_for_status()
    failed = httpx.get(
        f"{api_base}/messages/failed",
        params={"limit": DEFAULT_LIMIT},
        timeout=5,
    )
    failed.raise_for_status()
    items = list(success.json().get("items", []))
    items.extend(list(failed.json().get("items", [])))
    return items


def _wait_for_terminal(api_base: str, message_id: str, timeout_sec: int) -> dict | None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        items = _fetch_terminals(api_base)
        for item in items:
            if str(item.get("messageId")) == message_id:
                return item
        time.sleep(POLL_INTERVAL_SEC)
    return None


def main() -> int:
    args = _parse_args()
    try:
        message_id = _post_message(args.api_base, args.body, args.to)
        terminal = _wait_for_terminal(args.api_base, message_id, args.timeout_sec)
    except httpx.HTTPError as exc:
        print(f"Smoke check failed: {exc}", file=sys.stderr)
        return 1
    if terminal is None:
        print(f"Timed out waiting for terminal messageId={message_id}", file=sys.stderr)
        return 2
    print(
        f"Smoke OK messageId={message_id} "
        f"attemptCount={terminal.get('attemptCount')} "
        f"reason={terminal.get('reason')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
