"""Notification service + API outcomes (plans/TESTS.md §4.5, §5)."""

from __future__ import annotations

import base64
import json
import uuid

import httpx
import pytest

pytest.importorskip("asgi_lifespan")
from asgi_lifespan import LifespanManager

import inspectio_exercise.notification.config as notification_config
from inspectio_exercise.api.app import create_app as create_api_app
from inspectio_exercise.notification.app import create_app as create_notification_app
from inspectio_exercise.notification.keys import notification_object_key
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.notification.store.memory_store import MemoryOutcomesHotStore
from inspectio_exercise.persistence.app import create_app as create_persistence
from obsolete_tests.e2e.constants import E2E_POLL_INTERVAL_SEC, E2E_POLL_TIMEOUT_SEC
from obsolete_tests.e2e.stack import e2e_stack, wait_for_message_in_outcomes
from obsolete_tests.integration.spy_persistence import SpyPersistenceClient

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_publish_after_durable_terminal_write(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """state/notifications/... + hot store after terminal persistence (worker publish path)."""
    async with e2e_stack(monkeypatch, tmp_path) as st:
        pr = await st.api.post(
            "/messages",
            json={"to": "+15554443322", "body": "integration-notify-publish"},
        )
        assert pr.status_code == 202, pr.text
        mid = pr.json()["messageId"]
        await wait_for_message_in_outcomes(
            st.api,
            message_id=mid,
            outcome="success",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )

        listed = await st.persistence.post(
            "/internal/v1/list-prefix",
            json={"prefix": "state/notifications/", "max_keys": 100},
        )
        assert listed.status_code == 200
        keys = [row["Key"] for row in listed.json()["keys"]]
        assert keys, "expected at least one notification log object under state/notifications/"
        found_mid = False
        for key in keys:
            go = await st.persistence.post("/internal/v1/get-object", json={"key": key})
            if go.status_code != 200:
                continue
            doc = json.loads(base64.b64decode(go.json()["body_b64"]))
            if doc.get("messageId") == mid:
                found_mid = True
                break
        assert found_mid


@pytest.mark.asyncio
async def test_api_get_outcomes_uses_notification_service_not_terminal_listing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /messages/success does not list-prefix terminal trees on the persistence client."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)

    def _notify_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.endswith("/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, text="unexpected")

    persist_app = create_persistence()
    async with LifespanManager(persist_app):
        pc = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        spy = SpyPersistenceClient(PersistenceHttpClient(pc))
        nc = httpx.AsyncClient(
            transport=httpx.MockTransport(_notify_handler),
            base_url="http://notification",
            timeout=30.0,
        )
        api_app = create_api_app(persistence=spy, notification_http=nc)
        async with LifespanManager(api_app):
            ac = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api_app),
                base_url="http://api",
                timeout=30.0,
            )
            await ac.post("/messages", json={"to": "+1", "body": "spy-outcomes"})
            spy.list_prefix_calls.clear()
            gr = await ac.get("/messages/success", params={"limit": 10})
            assert gr.status_code == 200
        terminal_lists = [
            p
            for p, _ in spy.list_prefix_calls
            if p.startswith("state/success/") or p.startswith("state/failed/")
        ]
        assert terminal_lists == []
        await nc.aclose()


@pytest.mark.asyncio
async def test_notification_service_hydration_order_and_cap(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup hydration loads newest rows first and respects HYDRATION_MAX."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("OUTCOMES_STORE_BACKEND", "memory")

    monkeypatch.setattr(notification_config, "HYDRATION_MAX", 2)
    monkeypatch.setattr(notification_config, "OUTCOMES_STREAM_MAX", 2)

    records = [
        {
            "messageId": "hydrate-old",
            "notificationId": str(uuid.uuid4()),
            "outcome": "success",
            "recordedAt": 1_000,
            "shardId": 0,
        },
        {
            "messageId": "hydrate-mid",
            "notificationId": str(uuid.uuid4()),
            "outcome": "success",
            "recordedAt": 2_000,
            "shardId": 0,
        },
        {
            "messageId": "hydrate-new",
            "notificationId": str(uuid.uuid4()),
            "outcome": "success",
            "recordedAt": 3_000,
            "shardId": 0,
        },
    ]

    persist_app = create_persistence()
    async with LifespanManager(persist_app):
        pc = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        for rec in records:
            nid = rec["notificationId"]
            rk = rec["recordedAt"]
            key = notification_object_key(nid, rk)
            raw = json.dumps(rec, separators=(",", ":")).encode("utf-8")
            put = await pc.post(
                "/internal/v1/put-object",
                json={
                    "key": key,
                    "body_b64": base64.b64encode(raw).decode("ascii"),
                    "content_type": "application/json",
                },
            )
            assert put.status_code == 200

        store = MemoryOutcomesHotStore(stream_max=2)
        notify_app = create_notification_app(
            test_outcomes_store=store,
            test_http_client=pc,
        )
        async with LifespanManager(notify_app):
            assert notify_app.state.hydration_count == 2
            hc = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=notify_app),
                base_url="http://notification",
                timeout=30.0,
            )
            rows = await hc.get("/internal/v1/outcomes/success", params={"limit": 10})
            assert rows.status_code == 200
            items = rows.json()
            assert len(items) == 2
            assert items[0]["recordedAt"] == 3_000
            assert items[1]["recordedAt"] == 2_000
