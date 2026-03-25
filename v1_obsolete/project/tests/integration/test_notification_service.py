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
from inspectio_exercise.notification.store.redis_store import RedisOutcomesHotStore
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
    store = RedisOutcomesHotStore(redis, owns_client=False)
    persist_app = create_persistence_app()

    async with (
        LifespanManager(persist_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_client,
    ):
        notify_app = create_notification_app(test_outcomes_store=store, test_http_client=p_client)
        async with (
            LifespanManager(notify_app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=notify_app),
                base_url="http://notify",
            ) as n_client,
        ):
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
async def test_success_stream_newest_first_after_two_publishes(
    local_s3_root: None,
) -> None:
    """LRANGE order must match NOTIFICATION_SERVICE.md §6 (newest first)."""
    redis = FakeAsyncRedis(decode_responses=True)
    store = RedisOutcomesHotStore(redis, owns_client=False)
    persist_app = create_persistence_app()

    async with (
        LifespanManager(persist_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_client,
    ):
        notify_app = create_notification_app(test_outcomes_store=store, test_http_client=p_client)
        async with (
            LifespanManager(notify_app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=notify_app),
                base_url="http://notify",
            ) as n_client,
        ):
            await n_client.post(
                "/internal/v1/outcomes",
                json={
                    "notificationId": "nid-old",
                    "messageId": "m-old",
                    "outcome": "success",
                    "recordedAt": 1_000,
                    "shardId": 0,
                },
            )
            await n_client.post(
                "/internal/v1/outcomes",
                json={
                    "notificationId": "nid-new",
                    "messageId": "m-new",
                    "outcome": "success",
                    "recordedAt": 2_000,
                    "shardId": 0,
                },
            )
            q = await n_client.get("/internal/v1/outcomes/success", params={"limit": 10})
            rows = q.json()
            assert [r["notificationId"] for r in rows] == ["nid-new", "nid-old"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hydration_reloads_redis_after_second_stack(
    local_s3_root: None,
    tmp_path,
) -> None:
    """Simulate restart: new notification app re-hydrates from persistence-only state."""
    redis = FakeAsyncRedis(decode_responses=True)
    store1 = RedisOutcomesHotStore(redis, owns_client=False)
    persist_app = create_persistence_app()

    async with (
        LifespanManager(persist_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_client,
    ):
        app1 = create_notification_app(test_outcomes_store=store1, test_http_client=p_client)
        async with (
            LifespanManager(app1),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app1),
                base_url="http://n1",
            ) as n1,
        ):
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
        store2 = RedisOutcomesHotStore(redis2, owns_client=False)
        app2 = create_notification_app(test_outcomes_store=store2, test_http_client=p_client)
        async with (
            LifespanManager(app2),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app2),
                base_url="http://n2",
            ) as n2,
        ):
            r = await n2.get("/internal/v1/outcomes/failed", params={"limit": 5})
            assert r.status_code == 200
            rows = r.json()
            assert len(rows) == 1
            assert rows[0]["notificationId"] == "nid-h1"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hydration_two_success_records_newest_first(
    local_s3_root: None,
) -> None:
    """After cold start, Redis list order must still be newest-first (hydrate LPUSH order)."""
    redis = FakeAsyncRedis(decode_responses=True)
    store1 = RedisOutcomesHotStore(redis, owns_client=False)
    persist_app = create_persistence_app()

    async with (
        LifespanManager(persist_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_client,
    ):
        app1 = create_notification_app(test_outcomes_store=store1, test_http_client=p_client)
        async with (
            LifespanManager(app1),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app1),
                base_url="http://n1",
            ) as n1,
        ):
            await n1.post(
                "/internal/v1/outcomes",
                json={
                    "notificationId": "h-old",
                    "messageId": "m1",
                    "outcome": "success",
                    "recordedAt": 1_705_000_000_000,
                    "shardId": 0,
                },
            )
            await n1.post(
                "/internal/v1/outcomes",
                json={
                    "notificationId": "h-new",
                    "messageId": "m2",
                    "outcome": "success",
                    "recordedAt": 1_706_000_000_000,
                    "shardId": 0,
                },
            )

        redis2 = FakeAsyncRedis(decode_responses=True)
        store2 = RedisOutcomesHotStore(redis2, owns_client=False)
        app2 = create_notification_app(test_outcomes_store=store2, test_http_client=p_client)
        async with (
            LifespanManager(app2),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app2),
                base_url="http://n2",
            ) as n2,
        ):
            r = await n2.get("/internal/v1/outcomes/success", params={"limit": 10})
            rows = r.json()
            assert [row["notificationId"] for row in rows] == ["h-new", "h-old"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_second_stack_skips_hydration_when_redis_shared_and_warm(
    local_s3_root: None,
) -> None:
    """Second notification process sharing Redis does not re-run destructive S3 hydration."""
    redis = FakeAsyncRedis(decode_responses=True)
    store1 = RedisOutcomesHotStore(redis, owns_client=False)
    persist_app = create_persistence_app()

    async with (
        LifespanManager(persist_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_client,
    ):
        app1 = create_notification_app(test_outcomes_store=store1, test_http_client=p_client)
        async with (
            LifespanManager(app1),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app1),
                base_url="http://n1",
            ) as n1,
        ):
            await n1.post(
                "/internal/v1/outcomes",
                json={
                    "notificationId": "nid-shared-replica",
                    "messageId": "m-shared",
                    "outcome": "failed",
                    "recordedAt": 1_705_312_900_000,
                    "shardId": 0,
                },
            )

        store2 = RedisOutcomesHotStore(redis, owns_client=False)
        app2 = create_notification_app(test_outcomes_store=store2, test_http_client=p_client)
        async with (
            LifespanManager(app2),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app2),
                base_url="http://n2",
            ) as n2,
        ):
            assert app2.state.hydration_count == 0
            r = await n2.get("/internal/v1/outcomes/failed", params={"limit": 5})
            assert r.status_code == 200
            assert any(row["notificationId"] == "nid-shared-replica" for row in r.json())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_duplicate_publish_same_notification_record_twice(
    local_s3_root: None,
) -> None:
    """TC-NTF-05: duplicate publish does not break ordering; both rows surface newest-first."""
    redis = FakeAsyncRedis(decode_responses=True)
    store = RedisOutcomesHotStore(redis, owns_client=False)
    persist_app = create_persistence_app()

    body = {
        "notificationId": "nid-dup",
        "messageId": "mid-dup",
        "outcome": "success",
        "recordedAt": 1_705_000_000_000,
        "shardId": 0,
    }

    async with (
        LifespanManager(persist_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_client,
    ):
        notify_app = create_notification_app(test_outcomes_store=store, test_http_client=p_client)
        async with (
            LifespanManager(notify_app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=notify_app),
                base_url="http://notify",
            ) as n_client,
        ):
            for _ in range(2):
                r = await n_client.post("/internal/v1/outcomes", json=body)
                assert r.status_code == 200, r.text
            q = await n_client.get("/internal/v1/outcomes/success", params={"limit": 10})
            rows = q.json()
            assert len(rows) == 2
            assert all(r["messageId"] == "mid-dup" for r in rows)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_notification_app_startup_fails_when_redis_unreachable(
    local_s3_root: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-NTF-07: redis backend with unreachable broker fails fast at lifespan (no silent memory)."""
    monkeypatch.setenv("OUTCOMES_STORE_BACKEND", "redis")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")

    persist_app = create_persistence_app()
    async with (
        LifespanManager(persist_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_client,
    ):
        with pytest.raises(RuntimeError, match="outcomes store unavailable"):
            async with LifespanManager(
                create_notification_app(test_http_client=p_client),
            ):
                pass
