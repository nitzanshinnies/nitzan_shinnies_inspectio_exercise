"""P2: throttle backoff curve and cap (plans/v3_phases/P2_SQS_AND_LOCALSTACK.md)."""

from __future__ import annotations

import random

import pytest

from inspectio.v3.sqs.backoff import (
    BACKOFF_BASE_MS,
    BACKOFF_JITTER_FRACTION,
    BACKOFF_MAX_MS,
    compute_backoff_delay_ms,
)


@pytest.mark.unit
def test_first_retry_delay_uses_base_and_jitter_bounds() -> None:
    rng = random.Random(42)
    delay = compute_backoff_delay_ms(0, rng=rng)
    max_jitter = int(BACKOFF_BASE_MS * BACKOFF_JITTER_FRACTION + 1)
    assert BACKOFF_BASE_MS <= delay <= BACKOFF_BASE_MS + max_jitter


@pytest.mark.unit
def test_large_attempt_index_stays_capped() -> None:
    rng = random.Random(1)
    assert compute_backoff_delay_ms(25, rng=rng) <= BACKOFF_MAX_MS


@pytest.mark.unit
def test_negative_attempt_rejected() -> None:
    with pytest.raises(ValueError):
        compute_backoff_delay_ms(-1, rng=random.Random(0))


@pytest.mark.unit
def test_delay_never_exceeds_max_ms() -> None:
    rng = random.Random(999)
    for attempt in range(20):
        assert compute_backoff_delay_ms(attempt, rng=rng) <= BACKOFF_MAX_MS
