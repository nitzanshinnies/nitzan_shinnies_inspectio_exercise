"""REST API contract (plans/REST_API.md §3).

Strict TDD: these tests **fail** until the API implements validation, persistence,
notification-service outcomes, and documented response shapes — not stub 501s.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

pytest.importorskip("asgi_lifespan")
from asgi_lifespan import LifespanManager

import inspectio_exercise.api.config as api_config
from inspectio_exercise.api.app import create_app
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient


def _respond_persistence_put(
    request: httpx.Request,
    puts: list[dict] | None,
) -> httpx.Response | None:
    """Handle ``put-object`` / ``put-objects``; optionally record decoded pending JSON rows."""
    path = request.url.path
    if path == "/internal/v1/put-object":
        if puts is not None:
            outer = json.loads(request.content.decode("utf-8"))
            inner = json.loads(base64.b64decode(outer["body_b64"]))
            puts.append(inner)
        return httpx.Response(200, json={"status": "ok"})
    if path == "/internal/v1/put-objects":
        payload = json.loads(request.content.decode("utf-8"))
        objects = payload["objects"]
        if puts is not None:
            for obj in objects:
                inner = json.loads(base64.b64decode(obj["body_b64"]))
                puts.append(inner)
        return httpx.Response(200, json={"status": "ok", "written": len(objects)})
    return None


@pytest.mark.unit
def test_post_messages_valid_body_returns_accepted_metadata(api_client: TestClient) -> None:
    """REST_API.md §3.1 — accepted message metadata including messageId; pending or accepted state."""
    response = api_client.post("/messages", json={"body": "hello"})
    assert response.status_code == 202
    data = response.json()
    assert "messageId" in data
    uuid.UUID(str(data["messageId"]))
    assert data.get("status") == "pending"


@pytest.mark.unit
def test_post_messages_explicit_to(api_client: TestClient) -> None:
    response = api_client.post(
        "/messages",
        json={"to": "+15551234567", "body": "hello"},
    )
    assert response.status_code == 202


@pytest.mark.unit
def test_post_messages_should_fail_persisted_in_payload() -> None:
    """Optional ``shouldFail`` is stored on pending ``payload`` for the worker to forward."""
    puts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        put_resp = _respond_persistence_put(request, puts)
        if put_resp is not None:
            return put_resp
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    with TestClient(app) as client:
        response = client.post("/messages", json={"body": "hello", "shouldFail": True})
    assert response.status_code == 202
    assert len(puts) == 1
    assert puts[0]["payload"]["shouldFail"] is True


@pytest.mark.unit
def test_post_messages_omits_should_fail_from_payload_when_absent() -> None:
    puts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        put_resp = _respond_persistence_put(request, puts)
        if put_resp is not None:
            return put_resp
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    with TestClient(app) as client:
        response = client.post("/messages", json={"body": "hello"})
    assert response.status_code == 202
    assert "shouldFail" not in puts[0]["payload"]


@pytest.mark.unit
def test_post_messages_missing_required_fields_rejected(api_client: TestClient) -> None:
    response = api_client.post("/messages", json={"to": "+1"})
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_empty_to_rejected(api_client: TestClient) -> None:
    response = api_client.post("/messages", json={"to": "", "body": "x"})
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_extra_json_fields_ignored(api_client: TestClient) -> None:
    """TC-NM-06: unknown keys do not break acceptance."""
    response = api_client.post(
        "/messages",
        json={"body": "hello", "unexpectedField": 99},
    )
    assert response.status_code == 202


@pytest.mark.unit
def test_post_messages_rejects_non_json_content_type(api_client: TestClient) -> None:
    """TC-NM-05: body must be JSON for the message schema."""
    response = api_client.post(
        "/messages",
        content="not-json",
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code in (400, 415, 422)


@pytest.mark.unit
def test_post_messages_unicode_body_round_trip_on_put(api_client: TestClient) -> None:
    """TC-API-16: non-ASCII body survives the pending put payload."""
    puts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        put_resp = _respond_persistence_put(request, puts)
        if put_resp is not None:
            return put_resp
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    text = "שלום 👋"
    with TestClient(app) as client:
        response = client.post("/messages", json={"to": "+15550001111", "body": text})
    assert response.status_code == 202
    assert len(puts) == 1
    assert puts[0]["payload"]["body"] == text
    assert puts[0]["payload"]["to"] == "+15550001111"


@pytest.mark.unit
def test_post_messages_unicode_to_round_trip_on_put() -> None:
    """TC-API-16: non-ASCII ``to`` is stored on the pending payload."""
    puts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        put_resp = _respond_persistence_put(request, puts)
        if put_resp is not None:
            return put_resp
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    to_val = "+972541234567 שלום"
    with TestClient(app) as client:
        response = client.post("/messages", json={"to": to_val, "body": "x"})
    assert response.status_code == 202
    assert puts[0]["payload"]["to"] == to_val


@pytest.mark.unit
def test_get_messages_success_returns_recent_outcomes(api_client: TestClient) -> None:
    """REST_API.md §3.3 — recent successes; default limit 100 when omitted."""
    response = api_client.get("/messages/success")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.unit
def test_get_messages_success_invalid_limit_rejected(api_client: TestClient) -> None:
    response = api_client.get("/messages/success?limit=0")
    assert response.status_code == 422


@pytest.mark.unit
def test_get_messages_failed_returns_recent_outcomes(api_client: TestClient) -> None:
    response = api_client.get("/messages/failed")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.unit
def test_get_messages_failed_invalid_limit_rejected(api_client: TestClient) -> None:
    response = api_client.get("/messages/failed?limit=-1")
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_repeat_returns_summary(api_client: TestClient) -> None:
    """REST_API.md §3.2 — ``?count=N`` with message body reused N times."""
    response = api_client.post(
        "/messages/repeat?count=3",
        json={"body": "hello"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data.get("accepted") == 3
    assert "messageIds" in data
    assert len(data["messageIds"]) == 3


@pytest.mark.unit
def test_post_messages_repeat_templates_should_fail_on_each_put() -> None:
    puts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        put_resp = _respond_persistence_put(request, puts)
        if put_resp is not None:
            return put_resp
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    with TestClient(app) as client:
        response = client.post(
            "/messages/repeat?count=2",
            json={"body": "hello", "shouldFail": True},
        )
    assert response.status_code == 200
    assert len(puts) == 2
    assert all(p["payload"].get("shouldFail") is True for p in puts)


@pytest.mark.unit
def test_post_messages_repeat_missing_count_rejected(api_client: TestClient) -> None:
    response = api_client.post("/messages/repeat", json={"body": "x"})
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_repeat_invalid_count_rejected(api_client: TestClient) -> None:
    response = api_client.post("/messages/repeat?count=0", json={"body": "x"})
    assert response.status_code == 422


@pytest.mark.unit
def test_delete_messages_method_not_allowed(api_client: TestClient) -> None:
    """TC-API-14: unsupported verb on an existing path."""
    response = api_client.delete("/messages")
    assert response.status_code == 405


@pytest.mark.unit
def test_get_messages_success_forwards_default_limit_to_notification() -> None:
    """TC-API-06: default outcome query limit matches config (100)."""
    limits: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        put_resp = _respond_persistence_put(request, None)
        if put_resp is not None:
            return put_resp
        if path.startswith("/internal/v1/outcomes/success"):
            limits.append(request.url.params.get("limit"))
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    with TestClient(app) as client:
        response = client.get("/messages/success")
    assert response.status_code == 200
    assert limits == [str(api_config.OUTCOME_QUERY_LIMIT_DEFAULT)]


@pytest.mark.unit
def test_get_messages_failed_forwards_default_limit_to_notification() -> None:
    """TC-API-07: default outcome query limit matches config (100)."""
    limits: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        put_resp = _respond_persistence_put(request, None)
        if put_resp is not None:
            return put_resp
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            limits.append(request.url.params.get("limit"))
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    with TestClient(app) as client:
        response = client.get("/messages/failed")
    assert response.status_code == 200
    assert limits == [str(api_config.OUTCOME_QUERY_LIMIT_DEFAULT)]


@pytest.mark.unit
def test_get_messages_success_accepts_unknown_query_params(api_client: TestClient) -> None:
    """TC-API-13: extra query keys do not break outcomes GET."""
    response = api_client.get("/messages/success?limit=5&futureFlag=1")
    assert response.status_code == 200


@pytest.mark.unit
def test_get_messages_success_limit_at_max_allowed(api_client: TestClient) -> None:
    """TC-API-08: limit at OUTCOME_QUERY_LIMIT_MAX is accepted."""
    response = api_client.get(
        "/messages/success",
        params={"limit": api_config.OUTCOME_QUERY_LIMIT_MAX},
    )
    assert response.status_code == 200


@pytest.mark.unit
def test_get_messages_success_limit_above_max_rejected(api_client: TestClient) -> None:
    """TC-API-08: limit above cap is rejected (FastAPI Query le=…)."""
    response = api_client.get(
        "/messages/success",
        params={"limit": api_config.OUTCOME_QUERY_LIMIT_MAX + 1},
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_get_messages_success_accepts_accept_header(api_client: TestClient) -> None:
    """TC-API-17: non-default Accept must not crash public GET."""
    response = api_client.get(
        "/messages/success",
        headers={"Accept": "application/json;q=0.9, */*;q=0.8"},
    )
    assert response.status_code == 200


@pytest.mark.unit
def test_post_messages_body_wrong_json_type_rejected(api_client: TestClient) -> None:
    """TC-API-02: schema types enforced (body must be string)."""
    response = api_client.post("/messages", json={"body": 12345})
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_repeat_float_count_rejected(api_client: TestClient) -> None:
    """TC-API-05: repeat count must be integer query."""
    response = api_client.post("/messages/repeat?count=2.5", json={"body": "x"})
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_repeat_count_above_cap_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-API-05: repeat count above REPEAT_COUNT_MAX → 422."""
    monkeypatch.setattr(api_config, "REPEAT_COUNT_MAX", 3)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        put_resp = _respond_persistence_put(request, None)
        if put_resp is not None:
            return put_resp
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    with TestClient(app) as client:
        response = client.post("/messages/repeat?count=4", json={"body": "x"})
    assert response.status_code == 422


@pytest.mark.unit
def test_post_messages_rejects_oversized_body(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-NM-07: body beyond ``MESSAGE_BODY_MAX_CHARS`` → 413."""
    monkeypatch.setattr(api_config, "MESSAGE_BODY_MAX_CHARS", 120)
    response = api_client.post("/messages", json={"body": "x" * 121})
    assert response.status_code == 413
    assert "Traceback" not in response.text


@pytest.mark.unit
def test_post_messages_repeat_rejects_oversized_body(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-NM-07: repeat path applies the same body size cap."""
    monkeypatch.setattr(api_config, "MESSAGE_BODY_MAX_CHARS", 80)
    response = api_client.post("/messages/repeat?count=1", json={"body": "y" * 81})
    assert response.status_code == 413


@pytest.mark.unit
def test_validation_error_json_has_no_traceback_strings(api_client: TestClient) -> None:
    """TC-SE-01 / TC-API-11: public 422 bodies must not embed Python tracebacks."""
    response = api_client.post("/messages", json={"body": 1})
    assert response.status_code == 422
    text = json.dumps(response.json())
    assert "Traceback" not in text
    assert 'File "' not in text


@pytest.mark.asyncio
@pytest.mark.unit
async def test_concurrent_post_messages_yield_distinct_ids() -> None:
    """TC-API-18: concurrent accepts do not collapse messageId values."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        put_resp = _respond_persistence_put(request, None)
        if put_resp is not None:
            return put_resp
        if path.startswith("/internal/v1/outcomes/success"):
            return httpx.Response(200, json=[])
        if path.startswith("/internal/v1/outcomes/failed"):
            return httpx.Response(200, json=[])
        return httpx.Response(500, text="unexpected")

    transport = httpx.MockTransport(handler)
    persist = httpx.AsyncClient(transport=transport, base_url="http://persistence")
    notif = httpx.AsyncClient(transport=transport, base_url="http://notification")
    app = create_app(persistence=PersistenceHttpClient(persist), notification_http=notif)
    async with (
        LifespanManager(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://api",
        ) as ac,
    ):
        responses = await asyncio.gather(
            *[ac.post("/messages", json={"body": f"cc-{i}"}) for i in range(12)]
        )
    for r in responses:
        assert r.status_code == 202, r.text
    ids = {r.json()["messageId"] for r in responses}
    assert len(ids) == 12
