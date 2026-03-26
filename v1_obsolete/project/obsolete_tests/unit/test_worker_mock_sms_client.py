"""Mock SMS client wire format (plans/TEST_LIST.md TC-WS-01)."""

from __future__ import annotations

import json

import httpx
import pytest

from inspectio_exercise.worker.mock_sms_client import post_mock_send

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_post_mock_send_includes_message_id_and_attempt_index() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/send":
            captured.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock-sms") as client:
        status = await post_mock_send(
            client,
            attempt_index=2,
            body="payload-text",
            message_id="mid-wire",
            should_fail=False,
            to="+15550009999",
        )
    assert status == 200
    assert len(captured) == 1
    body = captured[0]
    assert body["messageId"] == "mid-wire"
    assert body["attemptIndex"] == 2
    assert body["body"] == "payload-text"
    assert body["to"] == "+15550009999"
    assert "shouldFail" not in body


@pytest.mark.asyncio
async def test_post_mock_send_propagates_connect_error() -> None:
    """TC-WS-02: transport errors surface to the caller (no silent success)."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectError(
            "connection refused", request=httpx.Request("POST", "http://mock-sms/send")
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock-sms") as client:
        with pytest.raises(httpx.ConnectError):
            await post_mock_send(
                client,
                attempt_index=0,
                body="x",
                message_id="m",
                should_fail=False,
                to="+1",
            )


@pytest.mark.asyncio
async def test_post_mock_send_includes_should_fail_when_true() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/send":
            captured.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(500, json={"code": "fail"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://mock-sms") as client:
        status = await post_mock_send(
            client,
            attempt_index=0,
            body="x",
            message_id="m",
            should_fail=True,
            to="+1",
        )
    assert status == 500
    assert captured[0].get("shouldFail") is True
