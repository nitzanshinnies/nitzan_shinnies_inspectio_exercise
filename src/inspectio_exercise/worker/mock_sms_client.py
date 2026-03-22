"""HTTP client call to mock SMS ``POST /send``."""

from __future__ import annotations

import httpx


async def post_mock_send(
    client: httpx.AsyncClient,
    *,
    attempt_index: int,
    body: str,
    message_id: str,
    should_fail: bool = False,
    to: str,
) -> int:
    payload: dict[str, str | int | bool] = {
        "attemptIndex": attempt_index,
        "body": body,
        "messageId": message_id,
        "to": to,
    }
    if should_fail:
        payload["shouldFail"] = True
    response = await client.post("/send", json=payload)
    return response.status_code
