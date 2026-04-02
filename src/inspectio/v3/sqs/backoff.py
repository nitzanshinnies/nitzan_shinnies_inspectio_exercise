"""Exponential backoff with jitter for SQS throttle retries (P2)."""

from __future__ import annotations

import random

BACKOFF_BASE_MS = 50
BACKOFF_MAX_MS = 2000
BACKOFF_JITTER_FRACTION = 0.2


def compute_backoff_delay_ms(attempt_zero_indexed: int, *, rng: random.Random) -> int:
    """Delay before retry `attempt_zero_indexed` (0 = after first failure)."""
    if attempt_zero_indexed < 0:
        raise ValueError("attempt_zero_indexed must be >= 0")
    expo = BACKOFF_BASE_MS * (2**attempt_zero_indexed)
    capped = min(BACKOFF_MAX_MS, expo)
    jitter = int(rng.random() * capped * BACKOFF_JITTER_FRACTION)
    return min(BACKOFF_MAX_MS, capped + jitter)
