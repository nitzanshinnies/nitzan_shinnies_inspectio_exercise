"""SQS producer with bounded retry+jitter, backpressure, and DLQ policy (P12.2)."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from botocore.exceptions import ClientError

from inspectio.v3.persistence_transport.errors import (
    PersistenceTransportBackpressureError,
    PersistenceTransportPublishError,
)
from inspectio.v3.persistence_transport.metrics import PersistenceTransportMetrics
from inspectio.v3.persistence_transport.protocol import PersistenceTransportProducer
from inspectio.v3.schemas.persistence_event import PersistenceEventV1
from inspectio.v3.sqs.aws_throttle import is_aws_throttle_error

DurabilityMode = Literal["best_effort", "strict"]


class SqsPersistenceTransportProducer(PersistenceTransportProducer):
    """Queue-based handoff; failures are isolated by durability mode policy."""

    def __init__(
        self,
        *,
        queue_url: str,
        client: Any,
        durability_mode: DurabilityMode,
        max_attempts: int,
        backoff_base_ms: int,
        backoff_max_ms: int,
        backoff_jitter_fraction: float,
        max_inflight_events: int,
        max_batch_events: int,
        dlq_queue_url: str | None = None,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._queue_url = queue_url
        self._client = client
        self._durability_mode = durability_mode
        self._max_attempts = max(1, max_attempts)
        self._backoff_base_ms = max(1, backoff_base_ms)
        self._backoff_max_ms = max(self._backoff_base_ms, backoff_max_ms)
        self._backoff_jitter_fraction = max(0.0, min(backoff_jitter_fraction, 1.0))
        self._max_inflight_events = max(1, max_inflight_events)
        self._max_batch_events = max(1, min(10, max_batch_events))
        self._dlq_queue_url = dlq_queue_url.strip() if dlq_queue_url else None
        self._sleeper: Callable[[float], Awaitable[None]] = sleeper or asyncio.sleep
        self._rng = rng or random.Random()
        self._inflight = 0
        self._inflight_lock = asyncio.Lock()
        self.metrics = PersistenceTransportMetrics()

    async def publish(self, event: PersistenceEventV1) -> None:
        await self.publish_many([event])

    async def publish_many(self, events: Sequence[PersistenceEventV1]) -> None:
        if not events:
            return
        for i in range(0, len(events), self._max_batch_events):
            chunk = list(events[i : i + self._max_batch_events])
            await self._publish_chunk(chunk)

    async def _publish_chunk(self, events: list[PersistenceEventV1]) -> None:
        acquired = await self._try_acquire_inflight(len(events))
        if not acquired:
            self.metrics.dropped_backpressure += len(events)
            if self._durability_mode == "strict":
                raise PersistenceTransportBackpressureError(
                    "persistence transport inflight cap exceeded",
                )
            return
        try:
            await self._publish_chunk_with_retries(events)
        finally:
            await self._release_inflight(len(events))

    async def _publish_chunk_with_retries(
        self, events: list[PersistenceEventV1]
    ) -> None:
        payload_entries = [
            {
                "Id": f"{event.shard}-{event.segment_seq}-{event.segment_event_index}-{idx}",
                "MessageBody": json.dumps(
                    event.model_dump(mode="json", by_alias=True, exclude_none=True),
                ),
            }
            for idx, event in enumerate(events)
        ]

        for attempt in range(self._max_attempts):
            try:
                publish_started = time.perf_counter()
                if len(payload_entries) == 1:
                    await self._client.send_message(
                        QueueUrl=self._queue_url,
                        MessageBody=payload_entries[0]["MessageBody"],
                    )
                else:
                    resp = await self._client.send_message_batch(
                        QueueUrl=self._queue_url,
                        Entries=payload_entries,
                    )
                    if resp.get("Failed"):
                        raise PersistenceTransportPublishError(
                            f"send_message_batch failed entries: {resp['Failed']!r}",
                        )
                publish_ms = int((time.perf_counter() - publish_started) * 1000)
                self.metrics.observe_publish_duration(duration_ms=publish_ms)
                self.metrics.published_ok += len(events)
                return
            except Exception as exc:  # noqa: BLE001
                if not self._retryable(exc) or attempt + 1 >= self._max_attempts:
                    self.metrics.publish_failures += len(events)
                    await self._attempt_dlq(payload_entries)
                    if self._durability_mode == "strict":
                        raise PersistenceTransportPublishError(str(exc)) from exc
                    return
                self.metrics.publish_retries += len(events)
                delay_ms = self._compute_backoff_ms(attempt)
                await self._sleeper(delay_ms / 1000.0)

    def _retryable(self, exc: Exception) -> bool:
        if isinstance(exc, PersistenceTransportPublishError):
            return False
        if isinstance(exc, ClientError):
            return is_aws_throttle_error(exc)
        return True

    def _compute_backoff_ms(self, attempt_zero_indexed: int) -> int:
        expo = self._backoff_base_ms * (2**attempt_zero_indexed)
        capped = min(self._backoff_max_ms, expo)
        jitter = int(self._rng.random() * capped * self._backoff_jitter_fraction)
        return min(self._backoff_max_ms, capped + jitter)

    async def _attempt_dlq(self, payload_entries: list[dict[str, str]]) -> None:
        if not self._dlq_queue_url:
            return
        try:
            if len(payload_entries) == 1:
                await self._client.send_message(
                    QueueUrl=self._dlq_queue_url,
                    MessageBody=payload_entries[0]["MessageBody"],
                )
            else:
                await self._client.send_message_batch(
                    QueueUrl=self._dlq_queue_url,
                    Entries=payload_entries,
                )
            self.metrics.dlq_published_ok += len(payload_entries)
        except Exception:  # noqa: BLE001
            self.metrics.dlq_failures += len(payload_entries)

    async def _try_acquire_inflight(self, n: int) -> bool:
        async with self._inflight_lock:
            if self._inflight + n > self._max_inflight_events:
                return False
            self._inflight += n
            return True

    async def _release_inflight(self, n: int) -> None:
        async with self._inflight_lock:
            self._inflight = max(0, self._inflight - n)
