"""Unit tests for writer queue-age observability semantics."""

from __future__ import annotations

import pytest

from inspectio.v3.persistence_writer.main import (
    QueueOldestAgeSample,
    _maybe_refresh_queue_oldest_age,
)


class _QueueAgeConsumer:
    def __init__(self, *, age_ms: int | None, should_fail: bool = False) -> None:
        self.age_ms = age_ms
        self.should_fail = should_fail
        self.calls = 0

    async def queue_oldest_age_ms(self) -> int | None:
        self.calls += 1
        if self.should_fail:
            raise RuntimeError("queue age fetch failed")
        return self.age_ms


@pytest.mark.unit
@pytest.mark.asyncio
async def test_queue_age_sampler_uses_queue_metric_and_respects_interval() -> None:
    consumer = _QueueAgeConsumer(age_ms=42_000)
    sample = QueueOldestAgeSample()
    updated = await _maybe_refresh_queue_oldest_age(
        consumer=consumer,
        sample=sample,
        now_ms=1_000,
        sample_interval_ms=30_000,
        timeout_sec=1.0,
    )
    assert consumer.calls == 1
    assert updated.age_ms == 42_000
    assert updated.sampled_at_ms == 1_000

    unchanged = await _maybe_refresh_queue_oldest_age(
        consumer=consumer,
        sample=updated,
        now_ms=2_000,
        sample_interval_ms=30_000,
        timeout_sec=1.0,
    )
    assert consumer.calls == 1
    assert unchanged.sampled_at_ms == 1_000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_queue_age_sampler_retains_last_known_value_on_failure() -> None:
    consumer = _QueueAgeConsumer(age_ms=10_000)
    sample = QueueOldestAgeSample()
    sample = await _maybe_refresh_queue_oldest_age(
        consumer=consumer,
        sample=sample,
        now_ms=1_000,
        sample_interval_ms=1,
        timeout_sec=1.0,
    )
    assert sample.age_ms == 10_000
    assert sample.sampled_at_ms == 1_000

    failing_consumer = _QueueAgeConsumer(age_ms=None, should_fail=True)
    after_failure = await _maybe_refresh_queue_oldest_age(
        consumer=failing_consumer,
        sample=sample,
        now_ms=2_500,
        sample_interval_ms=1,
        timeout_sec=1.0,
    )
    assert failing_consumer.calls == 1
    assert after_failure.age_ms == 10_000
    assert after_failure.sampled_at_ms == 1_000
