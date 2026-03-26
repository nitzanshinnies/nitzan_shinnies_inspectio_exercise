"""SMS adapter client (§19) used by scheduler runtime."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from inspectio.models import Message


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
        try:
            async with httpx.AsyncClient(timeout=self.timeout_sec) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise TimeoutError("connect_timeout") from exc
        return 200 <= response.status_code < 300
