"""P5: L1 static root + proxy to L2 (in-process ASGI, no network)."""

from __future__ import annotations

import httpx
import pytest

from inspectio.v3.l1.app import create_l1_app
from inspectio.v3.l2.app import create_l2_app
from inspectio.v3.l2.memory_enqueue import ListBulkEnqueue


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_root_returns_demo_html() -> None:
    backend = ListBulkEnqueue()
    l2 = create_l2_app(
        enqueue_backend=backend,
        clock_ms=lambda: 1_700_000_000_000,
        shard_count=1,
    )
    transport_l2 = httpx.ASGITransport(app=l2)
    async with httpx.AsyncClient(
        transport=transport_l2, base_url="http://l2"
    ) as l2_client:
        l1 = create_l1_app(l2_client=l2_client)
        transport_l1 = httpx.ASGITransport(app=l1)
        async with httpx.AsyncClient(
            transport=transport_l1, base_url="http://l1"
        ) as client:
            r = await client.get("/")
    assert r.status_code == 200
    ct = r.headers.get("content-type") or ""
    assert "text/html" in ct
    assert b"Inspectio v3" in r.content
    assert b"/messages/repeat" in r.content


@pytest.mark.unit
@pytest.mark.asyncio
async def test_post_messages_via_l1_returns_202() -> None:
    backend = ListBulkEnqueue()
    l2 = create_l2_app(
        enqueue_backend=backend,
        clock_ms=lambda: 1_700_000_000_000,
        shard_count=1,
    )
    transport_l2 = httpx.ASGITransport(app=l2)
    async with httpx.AsyncClient(
        transport=transport_l2, base_url="http://l2"
    ) as l2_client:
        l1 = create_l1_app(l2_client=l2_client)
        transport_l1 = httpx.ASGITransport(app=l1)
        async with httpx.AsyncClient(
            transport=transport_l1, base_url="http://l1"
        ) as client:
            r = await client.post("/messages", json={"body": "proxy-smoke"})
    assert r.status_code == 202
    data = r.json()
    assert "messageId" in data
    assert len(backend.items) == 1
