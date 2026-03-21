"""POST /send decision + audit (plans/MOCK_SMS.md §3–§4, §8)."""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
from typing import Any

from inspectio_exercise.mock_sms import config
from inspectio_exercise.mock_sms.audit import append_audit_row

_rng: random.Random = (
    random.Random(config.RNG_SEED) if config.RNG_SEED is not None else random.Random()
)
_rng_lock = asyncio.Lock()


def _to_ref(to: str) -> str:
    if config.AUDIT_REDACT_TO:
        return hashlib.sha256(to.encode("utf-8")).hexdigest()[:16]
    return to[:48]


async def decide_send_outcome(
    *,
    should_fail: bool,
) -> tuple[int, str]:
    """Return ``(http_status, outcome_kind)`` for a validated send request."""
    async with _rng_lock:
        if should_fail:
            if _rng.random() < config.UNAVAILABLE_FRACTION:
                return 503, "forced_fail_unavailable"
            return 500, "forced_fail"
        if _rng.random() < config.FAILURE_RATE:
            if _rng.random() < config.UNAVAILABLE_FRACTION:
                return 503, "service_unavailable"
            return 500, "failed_to_send"
        return 200, "success"


async def handle_send_request(payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    """Latency sleep, outcome decision, audit row; returns status + optional JSON body."""
    if config.LATENCY_MS > 0:
        await asyncio.sleep(config.LATENCY_MS / 1000.0)

    to = payload.get("to")
    body = payload.get("body")
    if not isinstance(to, str) or not isinstance(body, str) or to == "" or body == "":
        now = int(time.time() * 1000)
        append_audit_row(
            {
                "attemptIndex": payload.get("attemptIndex"),
                "http_status": 400,
                "messageId": payload.get("messageId"),
                "outcome_kind": "validation_error",
                "receivedAt_ms": now,
                "to_ref": _to_ref(str(to)) if isinstance(to, str) else None,
            }
        )
        return 400, {"detail": "to and body are required non-empty strings"}

    should_fail = bool(payload.get("shouldFail"))
    status, kind = await decide_send_outcome(should_fail=should_fail)
    now = int(time.time() * 1000)
    append_audit_row(
        {
            "attemptIndex": payload.get("attemptIndex"),
            "http_status": status,
            "messageId": payload.get("messageId"),
            "outcome_kind": kind,
            "receivedAt_ms": now,
            "to_ref": _to_ref(to),
        }
    )
    if status == 200:
        return 200, {"ok": True}
    code = "SERVICE_UNAVAILABLE" if status == 503 else "FAILED_TO_SEND"
    return status, {"code": code, "error": "simulated SMS failure"}
