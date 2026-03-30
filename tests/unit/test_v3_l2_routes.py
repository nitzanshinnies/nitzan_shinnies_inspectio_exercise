"""P1: L2 HTTP routes with stub enqueue (plans/v3_phases/P1_L2_HTTP_AND_STUB_ENQUEUE.md)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from inspectio.v3.l2.app import create_l2_app
from inspectio.v3.l2.memory_enqueue import ListBulkEnqueue
from inspectio.v3.schemas.bulk_intent import BulkIntentV1


@pytest.fixture
def clock_ms() -> tuple[list[int], Callable[[], int]]:
    holder = [1_700_000_000_000]

    def tick() -> int:
        return holder[0]

    return holder, tick


@pytest.fixture
def client_and_queue(
    clock_ms: tuple[list[int], Callable[[], int]],
) -> tuple[TestClient, ListBulkEnqueue, Callable[[], int]]:
    _holder, tick = clock_ms
    backend = ListBulkEnqueue()
    app = create_l2_app(
        enqueue_backend=backend,
        clock_ms=tick,
        shard_count=1,
        idempotency_ttl_ms=3_600_000,
    )
    return TestClient(app), backend, tick


@pytest.mark.unit
def test_healthz_ok(client_and_queue: tuple[TestClient, Any, Any]) -> None:
    client, _, _ = client_and_queue
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "api"}


@pytest.mark.unit
def test_post_messages_enqueues_bulk_count_one(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, backend, _ = client_and_queue
    response = client.post("/messages", json={"body": " hi "})
    assert response.status_code == 202
    data = response.json()
    assert data["shardId"] == 0
    uuid.UUID(data["messageId"])
    assert data["messageId"] == data["batchCorrelationId"]
    assert len(backend.items) == 1
    bulk = backend.items[0]
    assert bulk.count == 1
    assert bulk.body == "hi"


@pytest.mark.unit
def test_post_messages_repeat_enqueues_single_bulk(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, backend, _ = client_and_queue
    response = client.post("/messages/repeat?count=5", json={"body": "x"})
    assert response.status_code == 202
    data = response.json()
    assert data["accepted"] == 5
    assert data["count"] == 5
    uuid.UUID(data["batchCorrelationId"])
    assert len(backend.items) == 1
    assert backend.items[0].count == 5


@pytest.mark.unit
def test_idempotency_repeat_skips_second_enqueue(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, backend, _ = client_and_queue
    headers = {"Idempotency-Key": "idem-repeat-1"}
    first = client.post("/messages/repeat?count=3", json={"body": "x"}, headers=headers)
    second = client.post(
        "/messages/repeat?count=3", json={"body": "x"}, headers=headers
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["batchCorrelationId"] == second.json()["batchCorrelationId"]
    assert len(backend.items) == 1


@pytest.mark.unit
def test_idempotency_single_skips_second_enqueue(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, backend, _ = client_and_queue
    headers = {"Idempotency-Key": "idem-single-1"}
    first = client.post("/messages", json={"body": "a"}, headers=headers)
    second = client.post("/messages", json={"body": "a"}, headers=headers)
    assert first.status_code == second.status_code == 202
    assert first.json()["batchCorrelationId"] == second.json()["batchCorrelationId"]
    assert len(backend.items) == 1


@pytest.mark.unit
def test_idempotency_conflict_returns_409(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, _, _ = client_and_queue
    headers = {"Idempotency-Key": "idem-conflict"}
    assert (
        client.post("/messages", json={"body": "a"}, headers=headers).status_code == 202
    )
    conflict = client.post("/messages", json={"body": "b"}, headers=headers)
    assert conflict.status_code == 409


@pytest.mark.unit
def test_outcomes_get_stubs_empty_items(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, _, _ = client_and_queue
    assert client.get("/messages/success").json() == {"items": []}
    assert client.get("/messages/failed").json() == {"items": []}
    assert client.get("/messages/success?limit=50").json() == {"items": []}


@pytest.mark.unit
def test_repeat_count_zero_returns_validation_error(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, _, _ = client_and_queue
    response = client.post("/messages/repeat?count=0", json={"body": "x"})
    assert response.status_code == 400


@pytest.mark.unit
def test_repeat_count_above_max_returns_validation_error(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, _, _ = client_and_queue
    response = client.post("/messages/repeat?count=100001", json={"body": "x"})
    assert response.status_code == 400


@pytest.mark.unit
def test_empty_body_after_trim_returns_400(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, _, _ = client_and_queue
    response = client.post("/messages", json={"body": "   \t  "})
    assert response.status_code == 400


@pytest.mark.unit
def test_clock_used_for_received_at_ms(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, backend, _ = client_and_queue
    client.post("/messages", json={"body": "z"})
    assert backend.items[0].received_at_ms == 1_700_000_000_000


@pytest.mark.unit
def test_trace_header_propagates_to_bulk(
    client_and_queue: tuple[TestClient, Any, Any],
) -> None:
    client, backend, _ = client_and_queue
    client.post("/messages", json={"body": "t"}, headers={"X-Trace-Id": "trace-xyz"})
    assert backend.items[0].trace_id == "trace-xyz"


@pytest.mark.unit
def test_predicted_shard_with_k_gt_one(
    clock_ms: tuple[list[int], Callable[[], int]],
) -> None:
    _holder, tick = clock_ms
    backend = ListBulkEnqueue()
    app = create_l2_app(
        enqueue_backend=backend,
        clock_ms=tick,
        shard_count=4,
        idempotency_ttl_ms=60_000,
    )
    client = TestClient(app)
    response = client.post("/messages", json={"body": "body"})
    assert response.status_code == 202
    shard = response.json()["shardId"]
    assert 0 <= shard < 4
    bulk_id = response.json()["batchCorrelationId"]
    bulk = backend.items[0]
    assert bulk.batch_correlation_id == bulk_id


@pytest.mark.unit
def test_idempotency_expires_allows_new_enqueue(
    clock_ms: tuple[list[int], Callable[[], int]],
) -> None:
    holder, tick = clock_ms
    backend = ListBulkEnqueue()
    app = create_l2_app(
        enqueue_backend=backend,
        clock_ms=tick,
        shard_count=1,
        idempotency_ttl_ms=1_000,
    )
    client = TestClient(app)
    headers = {"Idempotency-Key": "expires-key"}
    assert (
        client.post("/messages", json={"body": "x"}, headers=headers).status_code == 202
    )
    holder[0] += 2_000
    assert (
        client.post("/messages", json={"body": "x"}, headers=headers).status_code == 202
    )
    assert len(backend.items) == 2
    assert isinstance(backend.items[0], BulkIntentV1)
    assert isinstance(backend.items[1], BulkIntentV1)
