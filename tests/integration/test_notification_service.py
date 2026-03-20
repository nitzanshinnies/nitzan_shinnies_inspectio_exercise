"""Notification service + persistence (in-process ASGI) — plans/NOTIFICATION_SERVICE.md."""

from __future__ import annotations

import os

import httpx
import pytest

pytest.importorskip("asgi_lifespan")
pytest.importorskip("fakeredis")
from asgi_lifespan import LifespanManager
from fakeredis import FakeAsyncRedis

from inspectio_exercise.notification.app import create_app as create_notification_app
from inspectio_exercise.persistence.app import create_app as create_persistence_app


@pytest.fixture
def local_s3_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))


@pytest.mark.integration
@pytest.mark.asyncio
async def test_publish_then_query_success(
    local_s3_root: None,
    tmp_path,
) -> None:
    redis = FakeAsyncRedis(decode_responses=True)
    persist_app = create_persistence_app()

    async with LifespanManager(persist_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_client:
            notify_app = create_notification_app(test_redis=redis, test_http_client=p_client)
            async with LifespanManager(notify_app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=notify_app),
                    base_url="http://notify",
                ) as n_client:
                    body = {
                        "notificationId": "01HZXK9YQTEST1234567890AB",
                        "messageId": "mid-1",
                        "outcome": "success",
                        "recordedAt": 1_705_312_800_000,
                        "shardId": 3,
                    }
                    r = await n_client.post("/internal/v1/outcomes", json=body)
                    assert r.status_code == 200, r.text

                    listed = list(tmp_path.rglob("*.json"))
                    assert len(listed) == 1
                    rel = str(listed[0].relative_to(tmp_path)).replace(os.sep, "/")
                    assert "state/notifications/" in rel

                    q = await n_client.get("/internal/v1/outcomes/success", params={"limit": 10})
                    assert q.status_code == 200
                    rows = q.json()
                    assert len(rows) == 1
                    assert rows[0]["notificationId"] == body["notificationId"]
                    assert rows[0]["outcome"] == "success"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hydration_reloads_redis_after_second_stack(
    local_s3_root: None,
    tmp_path,
) -> None:
    """Simulate restart: new notification app re-hydrates from persistence-only state."""
    redis = FakeAsyncRedis(decode_responses=True)
    persist_app = create_persistence_app()

    async with LifespanManager(persist_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_client:
            app1 = create_notification_app(test_redis=redis, test_http_client=p_client)
            async with LifespanManager(app1):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app1),
                    base_url="http://n1",
                ) as n1:
                    await n1.post(
                        "/internal/v1/outcomes",
                        json={
                            "notificationId": "nid-h1",
                            "messageId": "m1",
                            "outcome": "failed",
                            "recordedAt": 1_705_312_900_000,
                            "shardId": 0,
                        },
                    )

            redis2 = FakeAsyncRedis(decode_responses=True)
            app2 = create_notification_app(test_redis=redis2, test_http_client=p_client)
            async with LifespanManager(app2):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app2),
                    base_url="http://n2",
                ) as n2:
                    r = await n2.get("/internal/v1/outcomes/failed", params={"limit": 5})
                    assert r.status_code == 200
                    rows = r.json()
                    assert len(rows) == 1
                    assert rows[0]["notificationId"] == "nid-h1"
