"""Mock SMS POST /send + audit (plans/MOCK_SMS.md §3, §8)."""

from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import inspectio_exercise.mock_sms.send_handler as send_handler_mod
from inspectio_exercise.mock_sms import config as mock_config
from inspectio_exercise.mock_sms.app import create_app

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_audit_sends_returns_newest_first(client: TestClient) -> None:
    client.post("/send", json={"to": "a", "body": "one", "messageId": "m-first"})
    client.post("/send", json={"to": "b", "body": "two", "messageId": "m-second"})
    rows = client.get("/audit/sends", params={"limit": 10})
    assert rows.status_code == 200
    data = rows.json()
    assert data[0]["messageId"] == "m-second"
    assert data[1]["messageId"] == "m-first"


def test_send_rejects_empty_to(client: TestClient) -> None:
    response = client.post("/send", json={"to": "", "body": "x"})
    assert response.status_code == 400


def test_send_should_fail_is_5xx(client: TestClient) -> None:
    response = client.post(
        "/send",
        json={"to": "+1", "body": "hi", "shouldFail": True, "messageId": "x", "attemptIndex": 0},
    )
    assert response.status_code >= 500
    body = response.json()
    assert "code" in body or "error" in body


def test_send_success_200(client: TestClient) -> None:
    with mock.patch.object(mock_config, "FAILURE_RATE", 0.0):
        response = client.post(
            "/send",
            json={"to": "+1", "body": "hi", "messageId": "ok-1", "attemptIndex": 0},
        )
    assert response.status_code == 200
    assert response.json().get("ok") is True


def test_send_valid_payload_never_4xx_on_simulate_path(client: TestClient) -> None:
    """TC-SMS-06: validated simulate requests stay on 2xx/5xx outcome families, not 400."""
    with (
        mock.patch.object(mock_config, "FAILURE_RATE", 0.0),
        mock.patch.object(mock_config, "UNAVAILABLE_FRACTION", 0.0),
    ):
        response = client.post(
            "/send",
            json={"to": "+1999", "body": "ok", "messageId": "m-sim", "attemptIndex": 0},
        )
    assert response.status_code != 400


def test_failure_rate_one_always_5xx_without_should_fail(client: TestClient) -> None:
    """TC-SMS-09: FAILURE_RATE=1 forces simulated failure when shouldFail is false."""
    with (
        mock.patch.object(mock_config, "FAILURE_RATE", 1.0),
        mock.patch.object(mock_config, "UNAVAILABLE_FRACTION", 0.0),
    ):
        for i in range(5):
            response = client.post(
                "/send",
                json={"to": "+1", "body": "x", "messageId": f"m{i}", "attemptIndex": 0},
            )
            assert response.status_code >= 500


def test_unavailable_fraction_zero_uses_500_class_not_503(client: TestClient) -> None:
    """TC-SMS-10: UNAVAILABLE_FRACTION=0 → no 503 from random unavailable branch."""
    with (
        mock.patch.object(mock_config, "FAILURE_RATE", 1.0),
        mock.patch.object(mock_config, "UNAVAILABLE_FRACTION", 0.0),
        mock.patch.object(send_handler_mod, "_rng", random.Random(0)),
    ):
        response = client.post(
            "/send",
            json={"to": "+1", "body": "x", "messageId": "u0", "attemptIndex": 0},
        )
    assert response.status_code == 500


def test_unavailable_fraction_one_yields_503_on_random_failure(client: TestClient) -> None:
    """TC-SMS-10: UNAVAILABLE_FRACTION=1 routes random failures through 503."""
    with (
        mock.patch.object(mock_config, "FAILURE_RATE", 1.0),
        mock.patch.object(mock_config, "UNAVAILABLE_FRACTION", 1.0),
        mock.patch.object(send_handler_mod, "_rng", random.Random(0)),
    ):
        response = client.post(
            "/send",
            json={"to": "+1", "body": "x", "messageId": "u1", "attemptIndex": 0},
        )
    assert response.status_code == 503


def test_rng_seed_produces_repeatable_status_sequence(client: TestClient) -> None:
    """TC-SMS-04: fixed RNG + rates yields deterministic outcomes across calls."""

    def run_batch() -> list[int]:
        with (
            mock.patch.object(mock_config, "FAILURE_RATE", 0.5),
            mock.patch.object(mock_config, "UNAVAILABLE_FRACTION", 0.0),
            mock.patch.object(send_handler_mod, "_rng", random.Random(12345)),
        ):
            codes = []
            for i in range(6):
                r = client.post(
                    "/send",
                    json={"to": "+1", "body": "x", "messageId": f"s{i}", "attemptIndex": 0},
                )
                codes.append(r.status_code)
            return codes

    assert run_batch() == run_batch()


def test_mixed_failure_and_unavailable_can_emit_500_and_503(client: TestClient) -> None:
    """TC-SMS-05: both failure families appear with mixed UNAVAILABLE_FRACTION."""
    codes: set[int] = set()
    with (
        mock.patch.object(mock_config, "FAILURE_RATE", 1.0),
        mock.patch.object(mock_config, "UNAVAILABLE_FRACTION", 0.5),
        mock.patch.object(send_handler_mod, "_rng", random.Random(7)),
    ):
        for i in range(40):
            r = client.post(
                "/send",
                json={"to": "+1", "body": "x", "messageId": f"mix{i}", "attemptIndex": 0},
            )
            codes.add(r.status_code)
    assert 500 in codes
    assert 503 in codes


def test_latency_ms_waits_before_outcome(client: TestClient) -> None:
    """TC-SMS-07: LATENCY_MS schedules an asyncio sleep on the send path."""
    with (
        mock.patch.object(mock_config, "LATENCY_MS", 12),
        mock.patch.object(mock_config, "FAILURE_RATE", 0.0),
        mock.patch(
            "inspectio_exercise.mock_sms.send_handler.asyncio.sleep",
            new_callable=mock.AsyncMock,
        ) as sleep_mock,
    ):
        response = client.post(
            "/send",
            json={"to": "+1", "body": "x", "messageId": "lat", "attemptIndex": 0},
        )
    assert response.status_code == 200
    sleep_mock.assert_awaited()


def test_concurrent_send_requests(client: TestClient) -> None:
    """TC-SMS-11: parallel /send calls complete without crashing."""
    with mock.patch.object(mock_config, "FAILURE_RATE", 0.0):

        def hit(i: int) -> int:
            r = client.post(
                "/send",
                json={"to": "+1", "body": "c", "messageId": f"thr{i}", "attemptIndex": 0},
            )
            return r.status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(hit, i) for i in range(24)]
            codes = [f.result() for f in as_completed(futs)]
    assert all(c == 200 for c in codes)
