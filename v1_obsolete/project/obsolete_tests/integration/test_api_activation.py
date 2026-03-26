"""API → pending → activation (plans/TESTS.md §5.3, REST_API.md §3).

Asserts public REST contract; fails until API implements validation + handlers (TDD).
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import cast

import httpx
import pytest

pytest.importorskip("asgi_lifespan")
from asgi_lifespan import LifespanManager

import inspectio_exercise.api.config as api_config
import inspectio_exercise.mock_sms.config as mock_sms_config
import inspectio_exercise.mock_sms.send_handler as send_handler
from inspectio_exercise.api.app import create_app as create_api_app
from inspectio_exercise.domain.retry import delay_ms_before_next_attempt_after_failure
from inspectio_exercise.domain.sharding import pending_prefix_for_shard, shard_id_for_message
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.persistence.app import create_app as create_persistence
from obsolete_tests.e2e.constants import (
    E2E_POLL_INTERVAL_SEC,
    E2E_POLL_TIMEOUT_SEC,
    E2E_SHARD_COUNT,
)
from obsolete_tests.e2e.stack import e2e_stack, wait_for_message_in_outcomes
from obsolete_tests.integration.spy_persistence import SpyPersistenceClient

pytestmark = pytest.mark.integration


def test_post_messages_returns_accepted_metadata(api_client) -> None:
    """§5.3 / REST_API §3.1 — accepted message metadata including messageId; pending (or accepted) state."""
    response = api_client.post("/messages", json={"to": "+1", "body": "hi"})
    assert response.status_code == 202
    data = response.json()
    assert "messageId" in data
    uuid.UUID(str(data["messageId"]))
    assert data.get("status") == "pending"


def test_get_outcomes_return_200_with_items(api_client) -> None:
    """REST_API §3.3–3.4 — recent outcomes; default limit when omitted."""
    response = api_client.get("/messages/success")
    assert response.status_code == 200
    assert "items" in response.json()
    assert api_client.get("/messages/failed").status_code == 200


def test_post_repeat_returns_summary(api_client) -> None:
    """REST_API §3.2 — summary with accepted count and distinct messageIds."""
    response = api_client.post("/messages/repeat?count=1", json={"body": "hi"})
    assert response.status_code == 200
    body = response.json()
    assert body.get("accepted") == 1
    assert len(body.get("messageIds", [])) == 1


@pytest.mark.asyncio
async def test_post_messages_creates_pending_under_shard_prefix(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /messages creates state/pending/shard-<shard_id>/<messageId>.json."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)

    total_shards = 256
    monkeypatch.setattr(api_config, "TOTAL_SHARDS", total_shards)

    def _notify_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[])

    persist_app = create_persistence()
    async with LifespanManager(persist_app):
        pc = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        nc = httpx.AsyncClient(
            transport=httpx.MockTransport(_notify_handler),
            base_url="http://notification",
            timeout=30.0,
        )
        api_app = create_api_app(
            persistence=PersistenceHttpClient(pc),
            notification_http=nc,
        )
        async with LifespanManager(api_app):
            ac = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api_app),
                base_url="http://api",
                timeout=30.0,
            )
            pr = await ac.post(
                "/messages",
                json={"to": "+15551234567", "body": "integration-shard-pending"},
            )
            assert pr.status_code == 202, pr.text
            mid = pr.json()["messageId"]
            sid = shard_id_for_message(mid, total_shards)
            prefix = pending_prefix_for_shard(sid)
            expected_key = f"{prefix}{mid}.json"
            listed = await pc.post(
                "/internal/v1/list-prefix",
                json={"prefix": prefix, "max_keys": 500},
            )
            assert listed.status_code == 200
            keys = [row["Key"] for row in listed.json()["keys"]]
            assert expected_key in keys
            got = await pc.post("/internal/v1/get-object", json={"key": expected_key})
            assert got.status_code == 200
            body = json.loads(base64.b64decode(got.json()["body_b64"]))
            assert body["messageId"] == mid
            assert body["status"] == "pending"
        await nc.aclose()


@pytest.mark.asyncio
async def test_post_messages_does_not_invoke_list_prefix(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-API-12: accept path uses put-object only, not list_prefix scans."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setattr(api_config, "TOTAL_SHARDS", 256)

    def _notify_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[])

    persist_app = create_persistence()
    async with LifespanManager(persist_app):
        pc = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        nc = httpx.AsyncClient(
            transport=httpx.MockTransport(_notify_handler),
            base_url="http://notification",
            timeout=30.0,
        )
        inner = PersistenceHttpClient(pc)
        spy = SpyPersistenceClient(inner)
        api_app = create_api_app(
            persistence=cast(PersistenceHttpClient, spy),
            notification_http=nc,
        )
        async with LifespanManager(api_app):
            ac = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api_app),
                base_url="http://api",
                timeout=30.0,
            )
            pr = await ac.post(
                "/messages",
                json={"to": "+15551230001", "body": "no-list-on-post"},
            )
            assert pr.status_code == 202, pr.text
        assert spy.list_prefix_calls == []
        await nc.aclose()


@pytest.mark.asyncio
async def test_post_messages_pending_without_worker_has_no_success_outcome(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-07: with API + persistence only, pending remains; success outcomes stay empty."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setattr(api_config, "TOTAL_SHARDS", 256)

    def _notify_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[])

    persist_app = create_persistence()
    async with LifespanManager(persist_app):
        pc = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        nc = httpx.AsyncClient(
            transport=httpx.MockTransport(_notify_handler),
            base_url="http://notification",
            timeout=30.0,
        )
        api_app = create_api_app(
            persistence=PersistenceHttpClient(pc),
            notification_http=nc,
        )
        async with LifespanManager(api_app):
            ac = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=api_app),
                base_url="http://api",
                timeout=30.0,
            )
            pr = await ac.post(
                "/messages",
                json={"to": "+15551230002", "body": "no-worker-yet"},
            )
            assert pr.status_code == 202, pr.text
            mid = pr.json()["messageId"]
            outcomes = await ac.get("/messages/success")
            assert outcomes.status_code == 200
            assert outcomes.json().get("items") == []
            sid = shard_id_for_message(mid, 256)
            expected_key = f"{pending_prefix_for_shard(sid)}{mid}.json"
            got = await pc.post("/internal/v1/get-object", json={"key": expected_key})
            assert got.status_code == 200
            body = json.loads(base64.b64decode(got.json()["body_b64"]))
            assert body["status"] == "pending"
        await nc.aclose()


@pytest.mark.asyncio
async def test_activation_attempt_one_mock_outcome(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock 2xx → success path; 5xx → retry with updated nextDueAt in pending."""
    monkeypatch.setattr(mock_sms_config, "FAILURE_RATE", 0.0)
    monkeypatch.setattr(mock_sms_config, "UNAVAILABLE_FRACTION", 0.0)

    async with e2e_stack(monkeypatch, tmp_path) as st:
        pr = await st.api.post(
            "/messages",
            json={"to": "+15559876543", "body": "integration-act-ok"},
        )
        assert pr.status_code == 202, pr.text
        mid_ok = pr.json()["messageId"]
        await wait_for_message_in_outcomes(
            st.api,
            message_id=mid_ok,
            outcome="success",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )

    orig = send_handler.decide_send_outcome
    attempt = {"n": 0}

    async def flaky_decide(*, should_fail: bool) -> tuple[int, str]:
        attempt["n"] += 1
        if attempt["n"] == 1:
            return 503, "unavailable"
        return await orig(should_fail=should_fail)

    monkeypatch.setattr(send_handler, "decide_send_outcome", flaky_decide)

    async with e2e_stack(monkeypatch, tmp_path) as st:
        pr = await st.api.post(
            "/messages",
            json={"to": "+15551112222", "body": "integration-act-retry"},
        )
        assert pr.status_code == 202, pr.text
        mid_retry = pr.json()["messageId"]
        await asyncio.sleep(0.4)
        sid = shard_id_for_message(mid_retry, E2E_SHARD_COUNT)
        pkey = f"state/pending/shard-{sid}/{mid_retry}.json"
        got = await st.persistence.post("/internal/v1/get-object", json={"key": pkey})
        assert got.status_code == 200
        pending = json.loads(base64.b64decode(got.json()["body_b64"]))
        assert pending["attemptCount"] == 1
        assert isinstance(pending["nextDueAt"], int)

        st.clock.advance_ms(delay_ms_before_next_attempt_after_failure(0))
        await asyncio.sleep(0.4)
        await wait_for_message_in_outcomes(
            st.api,
            message_id=mid_retry,
            outcome="success",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )
