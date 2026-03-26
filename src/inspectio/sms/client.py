"""SMS adapter client (§19) used by scheduler runtime."""

from __future__ import annotations

from dataclasses import dataclass
import time

import httpx

from inspectio.models import Message
from inspectio.perf_log import perf_line


@dataclass(frozen=True, slots=True)
class SmsClient:
    """HTTP client wrapper for provider/mock `/send` endpoint."""

    base_url: str
    timeout_sec: int

    async def send(self, message: Message, attempt_index: int) -> bool:
        url = f"{self.base_url.rstrip('/')}/send"
        payload = {
            "to": message.to,
            "body": message.body,
            "messageId": message.message_id,
            "attemptIndex": attempt_index,
        }
        start_ns = time.monotonic_ns()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
            perf_line(
                "sms_http",
                message_id=message.message_id,
                result="timeout",
                attempt_index=attempt_index,
                http_ms=f"{elapsed_ms:.3f}",
            )
            raise TimeoutError("connect_timeout") from exc
        elapsed_ms = (time.monotonic_ns() - start_ns) / 1_000_000
        ok = 200 <= response.status_code < 300
        perf_line(
            "sms_http",
            message_id=message.message_id,
            result="ok" if ok else "error",
            attempt_index=attempt_index,
            http_status=response.status_code,
            http_ms=f"{elapsed_ms:.3f}",
        )
        return ok
