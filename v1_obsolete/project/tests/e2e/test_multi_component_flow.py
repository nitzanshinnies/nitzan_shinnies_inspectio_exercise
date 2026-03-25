"""Multi-component E2E flows (plans/TESTS.md §6, TEST_LIST TC-E2E-*)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

pytest.importorskip("asgi_lifespan")

from inspectio_exercise.domain.retry import delay_ms_before_next_attempt_after_failure
from tests.e2e.constants import (
    E2E_BASE_TIME_SEC,
    E2E_POLL_INTERVAL_SEC,
    E2E_POLL_TIMEOUT_SEC,
)
from tests.e2e.stack import PatchedTime, e2e_stack, wait_for_message_in_outcomes

pytestmark = pytest.mark.e2e


async def _success_object_keys_for_mid(
    persistence: httpx.AsyncClient, message_id: str
) -> list[str]:
    listed = await persistence.post(
        "/internal/v1/list-prefix",
        json={"prefix": "state/success/", "max_keys": 500},
    )
    listed.raise_for_status()
    suffix = f"/{message_id}.json"
    keys: list[str] = []
    for row in listed.json().get("keys", []):
        k = row.get("Key")
        if isinstance(k, str) and k.endswith(suffix):
            keys.append(k)
    return keys


@pytest.mark.asyncio
async def test_e2e_success_terminal_and_recent_outcome(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-01: SMS 2xx → success terminal; GET /messages/success sees messageId."""
    async with e2e_stack(monkeypatch, tmp_path) as st:
        pr = await st.api.post("/messages", json={"to": "+15550001", "body": "e2e-ok"})
        assert pr.status_code == 202, pr.text
        mid = pr.json()["messageId"]

        await wait_for_message_in_outcomes(
            st.api,
            message_id=mid,
            outcome="success",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )

        hz = await st.api.get("/healthz")
        assert hz.status_code == 200
        assert hz.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_e2e_retry_then_success(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-02: first send 503, then success after nextDueAt."""
    import inspectio_exercise.mock_sms.send_handler as send_handler

    orig = send_handler.decide_send_outcome
    attempt = {"n": 0}

    async def flaky_decide(*, should_fail: bool) -> tuple[int, str]:
        attempt["n"] += 1
        if attempt["n"] == 1:
            return 503, "unavailable"
        return await orig(should_fail=should_fail)

    monkeypatch.setattr(send_handler, "decide_send_outcome", flaky_decide)

    async with e2e_stack(monkeypatch, tmp_path) as st:
        pr = await st.api.post("/messages", json={"to": "+15550002", "body": "e2e-retry"})
        assert pr.status_code == 202, pr.text
        mid = pr.json()["messageId"]

        await asyncio.sleep(0.35)
        st.clock.advance_ms(delay_ms_before_next_attempt_after_failure(0))
        await asyncio.sleep(0.35)

        await wait_for_message_in_outcomes(
            st.api,
            message_id=mid,
            outcome="success",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )


@pytest.mark.asyncio
async def test_e2e_terminal_failed_should_fail_payload(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-03 / TC-E2E-09: shouldFail forces failure until terminal failed."""

    # PLAN.md uses multi-second gaps before later attempts; nudge fake time until the mock
    # records six failed sends (attemptIndex 0..5), then assert notification outcome.
    def _next_due_compact(now_ms: int, attempt_count_when_failed: int) -> int | None:
        if attempt_count_when_failed == 5:
            return None
        return now_ms + 50

    monkeypatch.setattr(
        "inspectio_exercise.worker.lifecycle_transitions.next_due_at_ms_after_failure",
        _next_due_compact,
    )

    async with e2e_stack(monkeypatch, tmp_path) as st:
        pr = await st.api.post(
            "/messages",
            json={"to": "+15550003", "body": "e2e-fail", "shouldFail": True},
        )
        assert pr.status_code == 202, pr.text
        mid = pr.json()["messageId"]

        loop = asyncio.get_running_loop()
        drive_deadline = loop.time() + 25.0
        fail_rows: list[dict[str, object]] = []
        while loop.time() < drive_deadline:
            ar = await st.mock_sms.get("/audit/sends", params={"limit": 50})
            assert ar.status_code == 200
            rows = ar.json()
            fail_rows = [
                r
                for r in rows
                if r.get("messageId") == mid
                and isinstance(r.get("http_status"), int)
                and r["http_status"] >= 500
            ]
            if len(fail_rows) >= 6:
                indices = sorted(
                    int(r["attemptIndex"])
                    for r in fail_rows
                    if isinstance(r.get("attemptIndex"), int)
                )
                if len(indices) >= 6 and min(indices) == 0 and max(indices) >= 5:
                    break
            st.clock.advance_ms(120)
            await asyncio.sleep(0.08)
        else:
            pytest.fail(f"expected 6 failed mock sends for {mid!r}, got {fail_rows!r}")

        await wait_for_message_in_outcomes(
            st.api,
            message_id=mid,
            outcome="failed",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )


@pytest.mark.asyncio
async def test_e2e_repeat_distinct_message_ids(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-05: POST /messages/repeat yields N distinct ids and N successes."""
    async with e2e_stack(monkeypatch, tmp_path) as st:
        n = 5
        pr = await st.api.post(
            "/messages/repeat",
            params={"count": n},
            json={"to": "+15550004", "body": "e2e-repeat"},
        )
        assert pr.status_code == 200, pr.text
        body = pr.json()
        assert body.get("accepted") == n
        ids = body.get("messageIds", [])
        assert len(ids) == n
        assert len(set(ids)) == n

        for mid in ids:
            await wait_for_message_in_outcomes(
                st.api,
                message_id=mid,
                outcome="success",
                timeout_sec=E2E_POLL_TIMEOUT_SEC,
                poll_interval_sec=E2E_POLL_INTERVAL_SEC,
            )


@pytest.mark.asyncio
async def test_e2e_limit_returns_at_most_requested_rows(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-06: after multiple successes, limit=10 caps response size."""
    async with e2e_stack(monkeypatch, tmp_path) as st:
        n = 12
        pr = await st.api.post(
            "/messages/repeat",
            params={"count": n},
            json={"to": "+15550005", "body": "e2e-limit"},
        )
        assert pr.status_code == 200, pr.text
        for mid in pr.json()["messageIds"]:
            await wait_for_message_in_outcomes(
                st.api,
                message_id=mid,
                outcome="success",
                timeout_sec=E2E_POLL_TIMEOUT_SEC,
                poll_interval_sec=E2E_POLL_INTERVAL_SEC,
            )

        r = await st.api.get("/messages/success", params={"limit": 10})
        assert r.status_code == 200
        assert len(r.json().get("items", [])) == 10


@pytest.mark.asyncio
async def test_e2e_mock_audit_reflects_send(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-10: mock audit contains a row for the message after success."""
    async with e2e_stack(monkeypatch, tmp_path) as st:
        pr = await st.api.post("/messages", json={"to": "+15550006", "body": "e2e-audit"})
        mid = pr.json()["messageId"]
        await wait_for_message_in_outcomes(
            st.api,
            message_id=mid,
            outcome="success",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )

        ar = await st.mock_sms.get("/audit/sends", params={"limit": 50})
        assert ar.status_code == 200
        rows = ar.json()
        assert any(r.get("messageId") == mid and r.get("http_status") == 200 for r in rows)


@pytest.mark.asyncio
async def test_e2e_worker_restart_resumes_retry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-04: worker stops mid-retry chain; new worker + advanced clock completes."""
    import inspectio_exercise.mock_sms.send_handler as send_handler

    orig = send_handler.decide_send_outcome
    attempt = {"n": 0}

    async def flaky_decide(*, should_fail: bool) -> tuple[int, str]:
        attempt["n"] += 1
        if attempt["n"] == 1:
            return 503, "unavailable"
        return await orig(should_fail=should_fail)

    monkeypatch.setattr(send_handler, "decide_send_outcome", flaky_decide)

    shared_clock = PatchedTime(E2E_BASE_TIME_SEC)
    async with e2e_stack(monkeypatch, tmp_path, clock=shared_clock) as st:
        pr = await st.api.post("/messages", json={"to": "+15550007", "body": "e2e-restart"})
        assert pr.status_code == 202, pr.text
        mid = pr.json()["messageId"]
        await asyncio.sleep(0.35)

    shared_clock.advance_ms(delay_ms_before_next_attempt_after_failure(0))

    async with e2e_stack(monkeypatch, tmp_path, clock=shared_clock) as st2:
        await wait_for_message_in_outcomes(
            st2.api,
            message_id=mid,
            outcome="success",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )


@pytest.mark.asyncio
async def test_e2e_sms_outage_then_recovery(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-08: mock SMS returns 503 for several attempts, then succeeds."""
    import inspectio_exercise.mock_sms.send_handler as send_handler

    orig = send_handler.decide_send_outcome
    n = {"c": 0}

    async def outage_then_ok(*, should_fail: bool) -> tuple[int, str]:
        n["c"] += 1
        if n["c"] <= 4:
            return 503, "sms_outage"
        return await orig(should_fail=should_fail)

    monkeypatch.setattr(send_handler, "decide_send_outcome", outage_then_ok)

    def _next_due_compact(now_ms: int, attempt_count_when_failed: int) -> int | None:
        if attempt_count_when_failed == 5:
            return None
        return now_ms + 50

    monkeypatch.setattr(
        "inspectio_exercise.worker.lifecycle_transitions.next_due_at_ms_after_failure",
        _next_due_compact,
    )

    async with e2e_stack(monkeypatch, tmp_path) as st:
        pr = await st.api.post("/messages", json={"to": "+15550020", "body": "e2e-outage"})
        assert pr.status_code == 202, pr.text
        mid = pr.json()["messageId"]
        await asyncio.sleep(0.35)
        for _ in range(30):
            st.clock.advance_ms(500)
            await asyncio.sleep(0.12)

        await wait_for_message_in_outcomes(
            st.api,
            message_id=mid,
            outcome="success",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )


@pytest.mark.asyncio
async def test_e2e_health_monitor_healthz(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-HM-01: health monitor liveness without running reconcile (HEALTH_MONITOR.md §4.1)."""
    async with e2e_stack(monkeypatch, tmp_path) as st:
        hz = await st.health_monitor.get("/healthz")
        assert hz.status_code == 200
        assert hz.json().get("status") == "ok"
        assert hz.json().get("service") == "health_monitor"


@pytest.mark.asyncio
async def test_e2e_health_monitor_integrity_ok_after_success(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-HM-02: after steady-state success, POST integrity-check returns 200 (TESTS.md §6)."""
    async with e2e_stack(monkeypatch, tmp_path) as st:
        pr = await st.api.post("/messages", json={"to": "+15550008", "body": "e2e-hm-ok"})
        assert pr.status_code == 202, pr.text
        mid = pr.json()["messageId"]
        await wait_for_message_in_outcomes(
            st.api,
            message_id=mid,
            outcome="success",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )

        ir = await st.health_monitor.post(
            "/internal/v1/integrity-check",
            json={"graceMs": 500},
        )
        assert ir.status_code == 200, ir.text
        data = ir.json()
        assert data.get("ok") is True
        assert data.get("violations") == []


@pytest.mark.asyncio
async def test_e2e_health_monitor_integrity_fails_on_induced_drift(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TC-E2E-HM-03: audit vs S3 drift — delete success object, expect phantom violation (§1)."""
    async with e2e_stack(monkeypatch, tmp_path) as st:
        pr = await st.api.post("/messages", json={"to": "+15550009", "body": "e2e-hm-drift"})
        assert pr.status_code == 202, pr.text
        mid = pr.json()["messageId"]
        await wait_for_message_in_outcomes(
            st.api,
            message_id=mid,
            outcome="success",
            timeout_sec=E2E_POLL_TIMEOUT_SEC,
            poll_interval_sec=E2E_POLL_INTERVAL_SEC,
        )

        keys = await _success_object_keys_for_mid(st.persistence, mid)
        assert len(keys) == 1
        dr = await st.persistence.post("/internal/v1/delete-object", json={"key": keys[0]})
        assert dr.status_code == 200

        ir = await st.health_monitor.post(
            "/internal/v1/integrity-check",
            json={"graceMs": 0},
        )
        assert ir.status_code == 503, ir.text
        kinds = {v.get("kind") for v in ir.json().get("violations", [])}
        assert "audit_send_without_lifecycle" in kinds
