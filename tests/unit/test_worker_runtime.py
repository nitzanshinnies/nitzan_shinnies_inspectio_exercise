"""Worker scheduler against fakes + MockTransport (plans/CORE_LIFECYCLE.md)."""

from __future__ import annotations

import json
import time
from unittest import mock

import httpx
import pytest

from inspectio_exercise.domain.sharding import pending_prefix_for_shard, shard_id_for_message
from inspectio_exercise.domain.utc_paths import terminal_success_key
from inspectio_exercise.worker.config import WorkerSettings
from inspectio_exercise.worker.runtime import WorkerRuntime, message_id_from_pending_key
from tests.fakes import RecordingPersistence

pytestmark = pytest.mark.unit


class _FlakyListPersistence(RecordingPersistence):
    """First ``list_503_count`` ``list_prefix`` calls raise 503; then delegate."""

    def __init__(self, list_503_count: int) -> None:
        super().__init__()
        self._list_503_left = list_503_count

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict]:
        if self._list_503_left > 0:
            self._list_503_left -= 1
            req = httpx.Request("POST", "http://persistence/internal/v1/list-prefix")
            raise httpx.HTTPStatusError(
                "transient",
                request=req,
                response=httpx.Response(503, request=req),
            )
        return await super().list_prefix(prefix, max_keys)


def _mid_on_shard0(total_shards: int = 256) -> str:
    for i in range(100_000):
        mid = f"worker-rt-{i}"
        if shard_id_for_message(mid, total_shards) == 0:
            return mid
    msg = f"no message id maps to shard 0 for total_shards={total_shards}"
    raise RuntimeError(msg)


def test_message_id_from_pending_key() -> None:
    assert message_id_from_pending_key("state/pending/shard-0/abc.json") == "abc"
    assert message_id_from_pending_key("bad") is None


@pytest.mark.asyncio
async def test_run_tick_success_writes_terminal_and_notifies() -> None:
    mid = _mid_on_shard0()
    key = f"{pending_prefix_for_shard(0)}{mid}.json"
    now_ms = int(time.time() * 1000)
    record = {
        "attemptCount": 0,
        "history": [],
        "messageId": mid,
        "nextDueAt": now_ms,
        "payload": {"body": "b", "to": "+1"},
        "status": "pending",
    }
    persistence = RecordingPersistence()
    await persistence.put_object(key, json.dumps(record, separators=(",", ":")).encode("utf-8"))

    outcomes: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/send":
            return httpx.Response(200, json={"ok": True})
        if path == "/internal/v1/outcomes":
            outcomes.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://mock-sms") as sms,
        httpx.AsyncClient(transport=transport, base_url="http://notification") as notify,
    ):
        settings = WorkerSettings(
            hostname="worker-0",
            http_timeout_sec=30.0,
            mock_sms_url="http://mock-sms",
            notification_url="http://notification",
            persistence_url="http://persistence",
            shards_per_pod=256,
            total_shards=256,
        )
        runtime = WorkerRuntime(
            notify_client=notify,
            persistence=persistence,
            settings=settings,
            sms_client=sms,
            tick_interval_sec=0.01,
        )
        await runtime.run_tick()

    assert key in persistence.deleted
    success_puts = [k for k, _ in persistence.puts if k.startswith("state/success/")]
    assert len(success_puts) == 1
    terminal_body = json.loads(
        next(b for k, b in persistence.puts if k == success_puts[0]).decode("utf-8")
    )
    assert terminal_body["status"] == "success"
    assert "recordedAt" in terminal_body
    assert len(outcomes) == 1
    assert outcomes[0]["messageId"] == mid
    assert outcomes[0]["outcome"] == "success"


@pytest.mark.asyncio
async def test_run_tick_failed_send_schedules_retry() -> None:
    mid = _mid_on_shard0()
    key = f"{pending_prefix_for_shard(0)}{mid}.json"
    now_ms = int(time.time() * 1000)
    record = {
        "attemptCount": 0,
        "history": [],
        "messageId": mid,
        "nextDueAt": now_ms,
        "payload": {"body": "b", "to": "+1"},
        "status": "pending",
    }
    persistence = RecordingPersistence()
    await persistence.put_object(key, json.dumps(record, separators=(",", ":")).encode("utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/send":
            return httpx.Response(500, json={"code": "FAILED_TO_SEND"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://mock-sms") as sms,
        httpx.AsyncClient(transport=transport, base_url="http://notification") as notify,
    ):
        settings = WorkerSettings(
            hostname="worker-0",
            http_timeout_sec=30.0,
            mock_sms_url="http://mock-sms",
            notification_url="http://notification",
            persistence_url="http://persistence",
            shards_per_pod=256,
            total_shards=256,
        )
        runtime = WorkerRuntime(
            notify_client=notify,
            persistence=persistence,
            settings=settings,
            sms_client=sms,
            tick_interval_sec=0.01,
        )
        with mock.patch("inspectio_exercise.worker.clocks.now_ms", return_value=now_ms):
            await runtime.run_tick()

    pending_puts = [p for p in persistence.puts if p[0] == key]
    assert len(pending_puts) >= 2
    updated = json.loads(pending_puts[-1][1].decode("utf-8"))
    assert updated["attemptCount"] == 1
    assert updated["nextDueAt"] == now_ms + 500


@pytest.mark.asyncio
async def test_discover_list_prefix_retries_on_transient_503() -> None:
    mid = _mid_on_shard0()
    key = f"{pending_prefix_for_shard(0)}{mid}.json"
    now_ms = int(time.time() * 1000)
    record = {
        "attemptCount": 0,
        "history": [],
        "messageId": mid,
        "nextDueAt": now_ms,
        "payload": {"body": "b", "to": "+1"},
        "status": "pending",
    }
    persistence = _FlakyListPersistence(list_503_count=2)
    await persistence.put_object(key, json.dumps(record, separators=(",", ":")).encode("utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/send":
            return httpx.Response(200, json={"ok": True})
        if path == "/internal/v1/outcomes":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://mock-sms") as sms,
        httpx.AsyncClient(transport=transport, base_url="http://notification") as notify,
    ):
        settings = WorkerSettings(
            hostname="worker-0",
            http_timeout_sec=30.0,
            mock_sms_url="http://mock-sms",
            notification_url="http://notification",
            persistence_url="http://persistence",
            shards_per_pod=256,
            total_shards=256,
        )
        runtime = WorkerRuntime(
            notify_client=notify,
            persistence=persistence,
            persistence_read_backoff_sec=0.001,
            settings=settings,
            sms_client=sms,
            tick_interval_sec=0.01,
        )
        await runtime.run_tick()

    assert persistence._list_503_left == 0
    assert key in persistence.deleted


@pytest.mark.asyncio
async def test_existing_terminal_skips_sms_reconciles_pending() -> None:
    mid = _mid_on_shard0()
    pending_key = f"{pending_prefix_for_shard(0)}{mid}.json"
    now_ms = int(time.time() * 1000)
    record = {
        "attemptCount": 0,
        "history": [],
        "messageId": mid,
        "nextDueAt": now_ms,
        "payload": {"body": "b", "to": "+1"},
        "status": "pending",
    }
    persistence = RecordingPersistence()
    terminal_key = terminal_success_key(mid, now_ms)
    terminal_record = {
        **record,
        "recordedAt": now_ms,
        "status": "success",
    }
    await persistence.put_object(
        pending_key, json.dumps(record, separators=(",", ":")).encode("utf-8")
    )
    await persistence.put_object(
        terminal_key,
        json.dumps(terminal_record, separators=(",", ":")).encode("utf-8"),
    )

    send_hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal send_hits
        path = request.url.path
        if path == "/send":
            send_hits += 1
            return httpx.Response(200, json={"ok": True})
        if path == "/internal/v1/outcomes":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://mock-sms") as sms,
        httpx.AsyncClient(transport=transport, base_url="http://notification") as notify,
    ):
        settings = WorkerSettings(
            hostname="worker-0",
            http_timeout_sec=30.0,
            mock_sms_url="http://mock-sms",
            notification_url="http://notification",
            persistence_url="http://persistence",
            shards_per_pod=256,
            total_shards=256,
        )
        runtime = WorkerRuntime(
            notify_client=notify,
            persistence=persistence,
            settings=settings,
            sms_client=sms,
            terminal_lookback_hours=24,
            tick_interval_sec=0.01,
        )
        await runtime.run_tick()

    assert send_hits == 0
    assert pending_key in persistence.deleted


@pytest.mark.asyncio
async def test_dispatch_forwards_should_fail_to_mock_sms() -> None:
    mid = _mid_on_shard0()
    key = f"{pending_prefix_for_shard(0)}{mid}.json"
    now_ms = int(time.time() * 1000)
    record = {
        "attemptCount": 0,
        "history": [],
        "messageId": mid,
        "nextDueAt": now_ms,
        "payload": {"body": "b", "to": "+1", "shouldFail": True},
        "status": "pending",
    }
    persistence = RecordingPersistence()
    await persistence.put_object(key, json.dumps(record, separators=(",", ":")).encode("utf-8"))

    last_send: dict | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal last_send
        if request.url.path == "/send":
            last_send = json.loads(request.content.decode("utf-8"))
            return httpx.Response(503, json={"code": "SERVICE_UNAVAILABLE", "error": "simulated"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://mock-sms") as sms,
        httpx.AsyncClient(transport=transport, base_url="http://notification") as notify,
    ):
        settings = WorkerSettings(
            hostname="worker-0",
            http_timeout_sec=30.0,
            mock_sms_url="http://mock-sms",
            notification_url="http://notification",
            persistence_url="http://persistence",
            shards_per_pod=256,
            total_shards=256,
        )
        runtime = WorkerRuntime(
            notify_client=notify,
            persistence=persistence,
            settings=settings,
            sms_client=sms,
            tick_interval_sec=0.01,
        )
        await runtime._dispatch.handle_one(mid, record, key)

    assert last_send is not None
    assert last_send.get("shouldFail") is True
    assert last_send["messageId"] == mid
    assert key not in persistence.deleted


@pytest.mark.asyncio
async def test_invalid_payload_deletes_pending_and_drops_scheduler_state() -> None:
    mid = _mid_on_shard0()
    key = f"{pending_prefix_for_shard(0)}{mid}.json"
    now_ms = int(time.time() * 1000)
    record = {
        "attemptCount": 0,
        "history": [],
        "messageId": mid,
        "nextDueAt": now_ms,
        "payload": {"body": "ok", "to": "+1"},
        "status": "pending",
    }
    persistence = RecordingPersistence()
    await persistence.put_object(key, json.dumps(record, separators=(",", ":")).encode("utf-8"))

    bad_rec = {
        **record,
        "payload": {"body": "x", "to": 999},
    }

    send_hits = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal send_hits
        if request.url.path == "/send":
            send_hits += 1
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with (
        httpx.AsyncClient(transport=transport, base_url="http://mock-sms") as sms,
        httpx.AsyncClient(transport=transport, base_url="http://notification") as notify,
    ):
        settings = WorkerSettings(
            hostname="worker-0",
            http_timeout_sec=30.0,
            mock_sms_url="http://mock-sms",
            notification_url="http://notification",
            persistence_url="http://persistence",
            shards_per_pod=256,
            total_shards=256,
        )
        runtime = WorkerRuntime(
            notify_client=notify,
            persistence=persistence,
            settings=settings,
            sms_client=sms,
            tick_interval_sec=0.01,
        )
        await runtime._dispatch.handle_one(mid, bad_rec, key)

    assert send_hits == 0
    assert key in persistence.deleted
    async with runtime._queue.lock:
        assert mid not in runtime._queue.records
