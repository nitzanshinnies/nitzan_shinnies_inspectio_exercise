"""Health monitor: mock audit vs persistence/S3 (plans/TESTS.md §5.6, HEALTH_MONITOR.md)."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

pytest.importorskip("asgi_lifespan")
from asgi_lifespan import LifespanManager

from inspectio_exercise.domain.utc_paths import terminal_success_key
from inspectio_exercise.health_monitor.app import create_app as create_health_monitor
from inspectio_exercise.mock_sms.app import create_app as create_mock_sms
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.persistence.app import create_app as create_persistence

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_integrity_check_post_resolves_audit_against_s3(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In-process persistence + mock SMS + health monitor; POST returns 2xx when audit matches S3."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)

    async def _always_success(*, should_fail: bool) -> tuple[int, str]:
        del should_fail
        return 200, "success"

    monkeypatch.setattr(
        "inspectio_exercise.mock_sms.send_handler.decide_send_outcome",
        _always_success,
    )

    persist_app = create_persistence()
    mock_app = create_mock_sms()
    mid = "hm-int-1"
    recorded_at = 1_700_000_000_000
    terminal_key = terminal_success_key(mid, recorded_at)
    terminal_body = {
        "messageId": mid,
        "status": "success",
        "attemptCount": 0,
        "nextDueAt": 0,
        "payload": {"to": "+10000000000", "body": "hello"},
        "recordedAt": recorded_at,
    }
    raw_terminal = json.dumps(terminal_body, separators=(",", ":")).encode("utf-8")

    async with (
        LifespanManager(persist_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_http,
        LifespanManager(mock_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_app),
            base_url="http://mock-sms",
        ) as m_http,
    ):
        put = await p_http.post(
            "/internal/v1/put-object",
            json={
                "key": terminal_key,
                "body_b64": base64.b64encode(raw_terminal).decode("ascii"),
                "content_type": "application/json",
            },
        )
        assert put.status_code == 200

        send = await m_http.post(
            "/send",
            json={
                "to": "+10000000000",
                "body": "hello",
                "messageId": mid,
                "attemptIndex": 0,
            },
        )
        assert send.status_code == 200

        persistence = PersistenceHttpClient(p_http)
        hm_app = create_health_monitor(persistence=persistence, mock_sms=m_http)
        async with (
            LifespanManager(hm_app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=hm_app),
                base_url="http://health-monitor",
            ) as hm_http,
        ):
            res = await hm_http.post(
                "/internal/v1/integrity-check",
                json={"graceMs": 100},
            )
            assert res.status_code == 200
            data = res.json()
            assert data["ok"] is True
            assert data["violations"] == []
            assert data["summary"]["violations"] == 0
            assert "checkedAt" in data

            st = await hm_http.get("/internal/v1/integrity-status")
            assert st.status_code == 200
            assert st.json()["lastRun"]["ok"] is True


@pytest.mark.asyncio
async def test_integrity_check_flags_non_json_lifecycle_object(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreadable ``*.json`` under lifecycle prefixes must fail closed (violation), not be ignored."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)

    persist_app = create_persistence()
    mock_app = create_mock_sms()

    async with (
        LifespanManager(persist_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_http,
        LifespanManager(mock_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_app),
            base_url="http://mock-sms",
        ) as m_http,
    ):
        corrupt_key = "state/success/2023/11/28/10/bad.json"
        put = await p_http.post(
            "/internal/v1/put-object",
            json={
                "key": corrupt_key,
                "body_b64": base64.b64encode(b"not-json").decode("ascii"),
                "content_type": "application/json",
            },
        )
        assert put.status_code == 200

        persistence = PersistenceHttpClient(p_http)
        hm_app = create_health_monitor(persistence=persistence, mock_sms=m_http)
        async with (
            LifespanManager(hm_app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=hm_app),
                base_url="http://health-monitor",
            ) as hm_http,
        ):
            res = await hm_http.post("/internal/v1/integrity-check", json={})
            assert res.status_code == 503
            kinds = {v["kind"] for v in res.json()["violations"]}
            assert "lifecycle_object_invalid_json" in kinds


@pytest.mark.asyncio
async def test_integrity_check_flags_invalid_utf8_lifecycle_object(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-UTF-8 object bytes must surface as a lifecycle violation, not an uncaught 500."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)

    persist_app = create_persistence()
    mock_app = create_mock_sms()

    async with (
        LifespanManager(persist_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
        ) as p_http,
        LifespanManager(mock_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_app),
            base_url="http://mock-sms",
        ) as m_http,
    ):
        bad_key = "state/success/2023/11/28/11/utf8.json"
        put = await p_http.post(
            "/internal/v1/put-object",
            json={
                "key": bad_key,
                "body_b64": base64.b64encode(b"\xff\xfe\x00").decode("ascii"),
                "content_type": "application/json",
            },
        )
        assert put.status_code == 200

        persistence = PersistenceHttpClient(p_http)
        hm_app = create_health_monitor(persistence=persistence, mock_sms=m_http)
        async with (
            LifespanManager(hm_app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=hm_app),
                base_url="http://health-monitor",
            ) as hm_http,
        ):
            res = await hm_http.post("/internal/v1/integrity-check", json={})
            assert res.status_code == 503
            kinds = {v["kind"] for v in res.json()["violations"]}
            assert "lifecycle_object_invalid_utf8" in kinds
