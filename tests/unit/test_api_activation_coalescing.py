from __future__ import annotations

import asyncio

import pytest

import inspectio_exercise.api.config as api_config
import inspectio_exercise.api.use_cases as use_cases
from inspectio_exercise.api.use_cases import SubmittedMessage


@pytest.mark.asyncio
@pytest.mark.unit
async def test_activation_coalescer_merges_nearby_submissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_config, "WORKER_ACTIVATION_COALESCE_WINDOW_MS", 5)
    monkeypatch.setattr(api_config, "WORKER_ACTIVATION_COALESCE_MAX_PENDING", 1000)

    calls: list[list[str]] = []

    async def fake_batch_activation(
        worker_clients,
        *,
        submitted,
        shards_per_pod,
    ) -> None:
        del worker_clients, shards_per_pod
        calls.append(sorted(row.message_id for row in submitted))

    monkeypatch.setattr(use_cases, "request_immediate_activation_batch", fake_batch_activation)
    coalescer = use_cases.ActivationCoalescer()
    worker_clients = [object()]

    await coalescer.submit(
        worker_clients=worker_clients,
        submitted=[
            SubmittedMessage(message_id="m1", pending_key="k1", shard_id=1),
        ],
        shards_per_pod=256,
    )
    await coalescer.submit(
        worker_clients=worker_clients,
        submitted=[
            SubmittedMessage(message_id="m1", pending_key="k1", shard_id=1),
            SubmittedMessage(message_id="m2", pending_key="k2", shard_id=2),
        ],
        shards_per_pod=256,
    )
    await asyncio.sleep(0.03)

    assert calls == [["m1", "m2"]]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_activation_coalescer_flushes_immediately_at_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_config, "WORKER_ACTIVATION_COALESCE_WINDOW_MS", 500)
    monkeypatch.setattr(api_config, "WORKER_ACTIVATION_COALESCE_MAX_PENDING", 2)

    calls: list[int] = []

    async def fake_batch_activation(
        worker_clients,
        *,
        submitted,
        shards_per_pod,
    ) -> None:
        del worker_clients, shards_per_pod
        calls.append(len(submitted))

    monkeypatch.setattr(use_cases, "request_immediate_activation_batch", fake_batch_activation)
    coalescer = use_cases.ActivationCoalescer()
    worker_clients = [object()]

    await coalescer.submit(
        worker_clients=worker_clients,
        submitted=[
            SubmittedMessage(message_id="m1", pending_key="k1", shard_id=1),
        ],
        shards_per_pod=256,
    )
    await coalescer.submit(
        worker_clients=worker_clients,
        submitted=[
            SubmittedMessage(message_id="m2", pending_key="k2", shard_id=2),
        ],
        shards_per_pod=256,
    )

    assert calls == [2]
