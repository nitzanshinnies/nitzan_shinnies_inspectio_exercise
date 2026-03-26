"""Mock/real SMS HTTP client (§19)."""

from __future__ import annotations

import httpx

from inspectio.settings import Settings


async def post_send(
    client: httpx.AsyncClient,
    settings: Settings,
    *,
    to: str,
    body: str,
    message_id: str,
    attempt_index: int,
) -> tuple[bool, int | None, str | None]:
    """POST `{INSPECTIO_SMS_URL}/send`; return (ok, http_status, error_class)."""
    url = settings.sms_url.rstrip("/") + "/send"
    timeout = settings.sms_http_timeout_sec
    try:
        resp = await client.post(
            url,
            json={
                "to": to,
                "body": body,
                "messageId": message_id,
                "attemptIndex": attempt_index,
            },
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        return False, None, type(exc).__name__
    err: str | None = None if resp.status_code == 200 else "http_error"
    return resp.status_code == 200, resp.status_code, err
