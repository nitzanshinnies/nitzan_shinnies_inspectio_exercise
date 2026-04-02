"""Stable idempotency fingerprint for admission requests."""

from __future__ import annotations

import json


def admission_fingerprint(*, body: str, to: str | None, count: int) -> str:
    payload = {"body": body, "count": count, "to": to}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
