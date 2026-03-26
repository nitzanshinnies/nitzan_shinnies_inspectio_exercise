#!/usr/bin/env python3
"""P9 smoke: POST /messages then wait for terminal in GET /messages/success.

Run after `docker compose up -d --build` with API on :8000 (override with
INSPECTIO_SMOKE_API). Requires stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_API = "http://127.0.0.1:8000"
MAX_WAIT_SEC = 60
POLL_INTERVAL_SEC = 1.0


def _post_messages(api: str) -> str:
    url = f"{api.rstrip('/')}/messages"
    payload = json.dumps({"body": "compose smoke"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    mid = data.get("messageId")
    if not mid:
        msg = "missing messageId in response"
        raise RuntimeError(msg)
    return str(mid)


def _get_success(api: str, limit: int) -> list[dict]:
    url = f"{api.rstrip('/')}/messages/success?limit={limit}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return list(data.get("items", []))


def main() -> int:
    api = os.environ.get("INSPECTIO_SMOKE_API", DEFAULT_API).strip()
    try:
        message_id = _post_messages(api)
    except urllib.error.HTTPError as exc:
        print(f"POST /messages failed: {exc.code} {exc.read()!r}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"POST /messages failed: {exc}", file=sys.stderr)
        return 2

    deadline = time.monotonic() + MAX_WAIT_SEC
    while time.monotonic() < deadline:
        try:
            items = _get_success(api, 50)
        except urllib.error.HTTPError as exc:
            print(f"GET /messages/success failed: {exc.code}", file=sys.stderr)
            time.sleep(POLL_INTERVAL_SEC)
            continue
        for it in items:
            if it.get("messageId") == message_id:
                print(f"OK terminal visible for messageId={message_id}")
                return 0
        time.sleep(POLL_INTERVAL_SEC)

    print(f"timeout after {MAX_WAIT_SEC}s waiting for {message_id}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
