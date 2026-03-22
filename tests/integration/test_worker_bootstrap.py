"""Worker bootstrap and resilience (plans/TESTS.md §5.2, §5.4, RESILIENCE.md)."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx
import pytest

pytest.importorskip("asgi_lifespan")
from asgi_lifespan import LifespanManager

from inspectio_exercise.domain.sharding import owned_shard_ids, pod_index_from_hostname
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.persistence.app import create_app as create_persistence
from inspectio_exercise.worker.due_work_queue import DueWorkQueue
from inspectio_exercise.worker.pending_discovery import discover_owned_pending
from inspectio_exercise.worker.retrying_persistence import RetryingPersistence

pytestmark = pytest.mark.integration


def _pending_body(mid: str, attempt: int, next_due: int) -> bytes:
    rec = {
        "messageId": mid,
        "status": "pending",
        "attemptCount": attempt,
        "nextDueAt": next_due,
        "payload": {"to": "+1", "body": "x"},
    }
    return json.dumps(rec, separators=(",", ":")).encode("utf-8")


class _FlakyListPersistence:
    """Raises 503 on ``list_prefix`` a few times, then delegates (transient failure simulation)."""

    def __init__(self, inner: PersistenceHttpClient) -> None:
        self._inner = inner
        self.list_failures_left = 2

    async def delete_object(self, key: str) -> None:
        await self._inner.delete_object(key)

    async def get_object(self, key: str) -> bytes:
        return await self._inner.get_object(key)

    async def list_prefix(self, prefix: str, max_keys: int | None = None) -> list[dict[str, Any]]:
        if self.list_failures_left > 0:
            self.list_failures_left -= 1
            req = httpx.Request("POST", "http://persistence/internal/v1/list-prefix")
            resp = httpx.Response(503)
            raise httpx.HTTPStatusError("transient", request=req, response=resp)
        return await self._inner.list_prefix(prefix, max_keys)

    async def put_object(
        self, key: str, body: bytes, content_type: str = "application/json"
    ) -> None:
        await self._inner.put_object(key, body, content_type)


@pytest.mark.asyncio
async def test_bootstrap_rebuilds_scheduler_from_pending(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Varied nextDueAt; due work is collected earliest-first (min-heap semantics)."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("HOSTNAME", "worker-0")
    monkeypatch.setenv("TOTAL_SHARDS", "16")
    monkeypatch.setenv("SHARDS_PER_POD", "16")

    persist_app = create_persistence()
    async with LifespanManager(persist_app):
        pc = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        for mid, nd in (("early-mid", 100_000), ("late-mid", 200_000)):
            key = f"state/pending/shard-0/{mid}.json"
            put = await pc.post(
                "/internal/v1/put-object",
                json={
                    "key": key,
                    "body_b64": base64.b64encode(_pending_body(mid, 0, nd)).decode("ascii"),
                    "content_type": "application/json",
                },
            )
            assert put.status_code == 200

        inner = PersistenceHttpClient(pc)
        queue = DueWorkQueue()
        owned = owned_shard_ids(
            pod_index_from_hostname("worker-0"),
            shards_per_pod=16,
            total_shards=16,
        )
        persist = RetryingPersistence(
            inner,
            base_delay_sec=0.01,
            max_attempts=3,
        )
        await discover_owned_pending(owned, persist, queue)
        due = await queue.collect_due(250_000)
        assert [t[0] for t in due] == ["early-mid", "late-mid"]


@pytest.mark.asyncio
async def test_bootstrap_skips_malformed_pending_json(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-JSON pending bytes are skipped; worker queue does not ingest that id."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("HOSTNAME", "worker-0")
    monkeypatch.setenv("TOTAL_SHARDS", "16")
    monkeypatch.setenv("SHARDS_PER_POD", "16")

    persist_app = create_persistence()
    async with LifespanManager(persist_app):
        pc = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        bad_key = "state/pending/shard-0/garbage.json"
        put = await pc.post(
            "/internal/v1/put-object",
            json={
                "key": bad_key,
                "body_b64": base64.b64encode(b"not-json").decode("ascii"),
                "content_type": "application/json",
            },
        )
        assert put.status_code == 200

        inner = PersistenceHttpClient(pc)
        queue = DueWorkQueue()
        owned = owned_shard_ids(
            pod_index_from_hostname("worker-0"),
            shards_per_pod=16,
            total_shards=16,
        )
        persist = RetryingPersistence(inner, base_delay_sec=0.01, max_attempts=3)
        await discover_owned_pending(owned, persist, queue)
        assert "garbage" not in queue.records


@pytest.mark.asyncio
async def test_bootstrap_retries_transient_persistence_errors(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RESILIENCE.md §5: list_prefix 503 a few times then succeeds."""
    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTIO_PERSISTENCE_BACKEND", "local")
    monkeypatch.delenv("INSPECTIO_S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("HOSTNAME", "worker-0")
    monkeypatch.setenv("TOTAL_SHARDS", "1")
    monkeypatch.setenv("SHARDS_PER_POD", "1")

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    persist_app = create_persistence()
    async with LifespanManager(persist_app):
        pc = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        mid = "retry-mid"
        key = f"state/pending/shard-0/{mid}.json"
        put = await pc.post(
            "/internal/v1/put-object",
            json={
                "key": key,
                "body_b64": base64.b64encode(_pending_body(mid, 0, 0)).decode("ascii"),
                "content_type": "application/json",
            },
        )
        assert put.status_code == 200

        inner = PersistenceHttpClient(pc)
        flaky = _FlakyListPersistence(inner)
        queue = DueWorkQueue()
        owned = owned_shard_ids(
            pod_index_from_hostname("worker-0"),
            shards_per_pod=1,
            total_shards=1,
        )
        persist = RetryingPersistence(
            flaky,
            base_delay_sec=0.01,
            max_attempts=5,
        )
        await discover_owned_pending(owned, persist, queue)
        assert mid in queue.records
        assert flaky.list_failures_left == 0
