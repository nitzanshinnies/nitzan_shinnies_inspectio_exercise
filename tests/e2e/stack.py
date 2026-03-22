"""In-process ASGI stack: persistence, mock SMS, notification, API, worker (plans/TESTS.md §6)."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

pytest.importorskip("asgi_lifespan")
from asgi_lifespan import LifespanManager

import inspectio_exercise.api.config as api_config
import inspectio_exercise.api.use_cases as api_use_cases
import inspectio_exercise.mock_sms.config as mock_sms_config
import inspectio_exercise.worker.clocks as worker_clocks
from inspectio_exercise.api.app import create_app as create_api_app
from inspectio_exercise.health_monitor.app import create_app as create_health_monitor_app
from inspectio_exercise.mock_sms.app import create_app as create_mock_sms_app
from inspectio_exercise.mock_sms.audit import clear_audit_ring_for_tests
from inspectio_exercise.notification.app import create_app as create_notification_app
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.notification.store.memory_store import MemoryOutcomesHotStore
from inspectio_exercise.persistence.app import create_app as create_persistence_app
from inspectio_exercise.worker.app import create_app as create_worker_app
from tests.e2e.constants import (
    E2E_BASE_TIME_SEC,
    E2E_SHARD_COUNT,
    E2E_SHARDS_PER_POD,
    E2E_WORKER_HOSTNAME,
    E2E_WORKER_TICK_SEC,
)


@dataclass
class PatchedTime:
    """Shared fake clock for ``time.time`` (API pending + worker scheduling)."""

    seconds: float

    def time(self) -> float:
        return self.seconds

    def advance_ms(self, delta_ms: int) -> None:
        self.seconds += delta_ms / 1000.0


@dataclass
class E2EStack:
    """Live httpx ASGI clients; resources owned by the ``e2e_stack`` context."""

    api: httpx.AsyncClient
    clock: PatchedTime
    health_monitor: httpx.AsyncClient
    mock_sms: httpx.AsyncClient
    persistence: httpx.AsyncClient


@asynccontextmanager
async def e2e_stack(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    *,
    clock: PatchedTime | None = None,
    worker_tick_sec: float | None = None,
) -> Any:
    clock = clock if clock is not None else PatchedTime(E2E_BASE_TIME_SEC)

    clear_audit_ring_for_tests()

    monkeypatch.setenv("LOCAL_S3_ROOT", str(tmp_path))
    monkeypatch.setenv("HOSTNAME", E2E_WORKER_HOSTNAME)
    monkeypatch.setenv("TOTAL_SHARDS", str(E2E_SHARD_COUNT))
    monkeypatch.setenv("SHARDS_PER_POD", str(E2E_SHARDS_PER_POD))
    monkeypatch.setenv("PERSISTENCE_SERVICE_URL", "http://persistence")
    monkeypatch.setenv("MOCK_SMS_URL", "http://mock-sms")
    monkeypatch.setenv("NOTIFICATION_SERVICE_URL", "http://notification")
    tick = worker_tick_sec if worker_tick_sec is not None else E2E_WORKER_TICK_SEC
    monkeypatch.setenv("INSPECTIO_WORKER_TICK_SEC", str(tick))

    monkeypatch.setattr(mock_sms_config, "FAILURE_RATE", 0.0)
    monkeypatch.setattr(mock_sms_config, "UNAVAILABLE_FRACTION", 0.0)
    monkeypatch.setattr(api_config, "TOTAL_SHARDS", E2E_SHARD_COUNT)

    class FakeTimeModule:
        def __init__(self, c: PatchedTime) -> None:
            self._c = c

        def time(self) -> float:
            return self._c.time()

    fake_time_mod = FakeTimeModule(clock)
    monkeypatch.setattr(api_use_cases, "time", fake_time_mod)
    monkeypatch.setattr(worker_clocks, "time", fake_time_mod)

    persist_app = create_persistence_app()
    mock_sms_app = create_mock_sms_app()
    store = MemoryOutcomesHotStore()

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(LifespanManager(persist_app))

        pc_api = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        await stack.enter_async_context(pc_api)

        pc_worker = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        await stack.enter_async_context(pc_worker)

        pc_notify = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=persist_app),
            base_url="http://persistence",
            timeout=30.0,
        )
        await stack.enter_async_context(pc_notify)

        notify_app = create_notification_app(
            test_outcomes_store=store,
            test_http_client=pc_notify,
        )
        await stack.enter_async_context(LifespanManager(notify_app))

        nc_api = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=notify_app),
            base_url="http://notification",
            timeout=30.0,
        )
        await stack.enter_async_context(nc_api)

        nc_worker = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=notify_app),
            base_url="http://notification",
            timeout=30.0,
        )
        await stack.enter_async_context(nc_worker)

        await stack.enter_async_context(LifespanManager(mock_sms_app))
        sc_worker = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mock_sms_app),
            base_url="http://mock-sms",
            timeout=30.0,
        )
        await stack.enter_async_context(sc_worker)

        hm_app = create_health_monitor_app(
            persistence=PersistenceHttpClient(pc_api),
            mock_sms=sc_worker,
        )
        await stack.enter_async_context(LifespanManager(hm_app))
        hm_http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=hm_app),
            base_url="http://health-monitor",
            timeout=30.0,
        )
        await stack.enter_async_context(hm_http)

        worker_app = create_worker_app(
            test_notify_client=nc_worker,
            test_persistence_client=pc_worker,
            test_sms_client=sc_worker,
        )
        worker_activation_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=worker_app),
            base_url="http://worker",
            timeout=30.0,
        )
        await stack.enter_async_context(worker_activation_client)

        await stack.enter_async_context(LifespanManager(worker_app))

        api_app = create_api_app(
            persistence=PersistenceHttpClient(pc_api),
            notification_http=nc_api,
            worker_activation_http=worker_activation_client,
        )
        await stack.enter_async_context(LifespanManager(api_app))

        ac = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app),
            base_url="http://api",
            timeout=30.0,
        )
        await stack.enter_async_context(ac)

        yield E2EStack(
            api=ac,
            clock=clock,
            health_monitor=hm_http,
            mock_sms=sc_worker,
            persistence=pc_api,
        )


async def wait_for_message_in_outcomes(
    api: httpx.AsyncClient,
    *,
    message_id: str,
    outcome: str,
    timeout_sec: float,
    poll_interval_sec: float,
) -> None:
    """Poll public API until ``message_id`` appears in success or failed items."""
    path = "/messages/success" if outcome == "success" else "/messages/failed"
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_sec
    while True:
        r = await api.get(path, params={"limit": 100})
        r.raise_for_status()
        items = r.json().get("items", [])
        for row in items:
            if row.get("messageId") == message_id:
                return
        if loop.time() >= deadline:
            raise AssertionError(
                f"timeout waiting for {message_id!r} in {outcome} outcomes; last={items!r}"
            )
        await asyncio.sleep(poll_interval_sec)
