"""P3 API admission tests (TC-API-001..005, TC-API-008)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from inspectio.api.app import create_app
from inspectio.ingest.ingest_producer import (
    IngestBufferOverflowError,
    IngestPutInput,
    IngestUnavailableError,
)


@dataclass(frozen=True, slots=True)
class _StubPutResult:
    ingest_sequence: str | None
    message_id: str
    shard_id: int


class _StubProducer:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raise_mode: str | None = None

    async def put_messages(
        self, messages: list[IngestPutInput]
    ) -> list[_StubPutResult]:
        self.calls.append({"messages": messages})
        if self.raise_mode == "overflow":
            raise IngestBufferOverflowError("buffer full")
        if self.raise_mode == "unavailable":
            raise IngestUnavailableError("down")
        out: list[_StubPutResult] = []
        for item in messages:
            out.append(
                _StubPutResult(
                    ingest_sequence="seq-1",
                    message_id=item.message_id,
                    shard_id=item.shard_id,
                )
            )
        return out


@pytest.mark.unit
def test_tc_api_001_post_messages_returns_202_and_ids() -> None:
    app = create_app()
    producer = _StubProducer()
    app.state.ingest_producer = producer
    client = TestClient(app)

    resp = client.post("/messages", json={"body": "hello", "to": "+15550000000"})
    assert resp.status_code == 202
    payload = resp.json()
    assert "messageId" in payload
    assert "shardId" in payload
    assert len(payload["messageId"]) == 36
    assert payload["messageId"] == payload["messageId"].lower()
    assert isinstance(payload["shardId"], int)
    assert len(producer.calls) == 1


@pytest.mark.unit
@pytest.mark.parametrize("body", ["", "   "])
def test_tc_api_002_post_messages_rejects_missing_or_blank_body(body: str) -> None:
    app = create_app()
    app.state.ingest_producer = _StubProducer()
    client = TestClient(app)

    resp = client.post("/messages", json={"body": body})
    assert resp.status_code == 400


@pytest.mark.unit
def test_tc_api_002_post_messages_rejects_missing_body() -> None:
    app = create_app()
    app.state.ingest_producer = _StubProducer()
    client = TestClient(app)

    resp = client.post("/messages", json={"to": "+15550000000"})
    assert resp.status_code == 400


@pytest.mark.unit
def test_tc_api_003_repeat_count_100_returns_accepted_and_unique_ids() -> None:
    app = create_app()
    producer = _StubProducer()
    app.state.ingest_producer = producer
    client = TestClient(app)

    resp = client.post("/messages/repeat?count=100", json={"body": "bulk"})
    assert resp.status_code == 202
    payload = resp.json()
    assert payload["accepted"] == 100
    assert len(payload["messageIds"]) == 100
    assert len(set(payload["messageIds"])) == 100
    assert len(payload["shardIds"]) == 100
    assert len(producer.calls) == 1


@pytest.mark.unit
def test_tc_api_003_repeat_over_500_is_chunked_and_accepted() -> None:
    app = create_app()
    producer = _StubProducer()
    app.state.ingest_producer = producer
    client = TestClient(app)

    resp = client.post("/messages/repeat?count=501", json={"body": "bulk"})
    assert resp.status_code == 202
    payload = resp.json()
    assert payload["accepted"] == 501
    assert len(payload["messageIds"]) == 501
    assert len(set(payload["messageIds"])) == 501
    assert len(payload["shardIds"]) == 501
    assert len(producer.calls) == 2
    assert len(producer.calls[0]["messages"]) == 500
    assert len(producer.calls[1]["messages"]) == 1


@pytest.mark.unit
def test_tc_api_004_repeat_rejects_count_out_of_range() -> None:
    app = create_app()
    app.state.ingest_producer = _StubProducer()
    client = TestClient(app)

    assert (
        client.post("/messages/repeat?count=0", json={"body": "x"}).status_code == 400
    )
    assert (
        client.post("/messages/repeat?count=100001", json={"body": "x"}).status_code
        == 400
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "status"),
    [("overflow", 429), ("unavailable", 503)],
)
def test_tc_api_005_post_messages_maps_ingest_errors(mode: str, status: int) -> None:
    app = create_app()
    producer = _StubProducer()
    producer.raise_mode = mode
    app.state.ingest_producer = producer
    client = TestClient(app)

    resp = client.post("/messages", json={"body": "hello"})
    assert resp.status_code == status
    assert "error" in resp.json()


@pytest.mark.unit
def test_tc_api_008_post_messages_does_not_await_scheduler_send_path() -> None:
    app = create_app()
    app.state.ingest_producer = _StubProducer()

    async def _send_forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("send() should never be awaited from /messages in P3")

    app.state.scheduler_send = _send_forbidden
    client = TestClient(app)

    resp = client.post("/messages", json={"body": "safe"})
    assert resp.status_code == 202
