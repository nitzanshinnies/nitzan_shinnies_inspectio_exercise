"""HTTP client call to mock SMS ``POST /send``."""

from __future__ import annotations

import httpx


async def post_mock_send(
    client: httpx.AsyncClient,
    *,
    attempt_index: int,
    body: str,
    message_id: str,
    to: str,
) -> int:
    response = await client.post(
        "/send",
        json={
            "to": to,
            "body": body,
            "messageId": message_id,
            "attemptIndex": attempt_index,
        },
    )
    return response.status_code
