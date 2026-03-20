"""Module-level behavior constants per plans/MOCK_SMS.md §5 (no env tuning)."""

from __future__ import annotations

# Validate at import (fail fast).
FAILURE_RATE: float = 0.2
UNAVAILABLE_FRACTION: float = 0.5
RNG_SEED: int | None = None
LISTEN_PORT: int = 8080
LATENCY_MS: int = 0

AUDIT_LOG_MAX_ENTRIES: int = 100_000
EXPOSE_AUDIT_ENDPOINT: bool = True
AUDIT_REDACT_TO: bool = True

assert 0.0 <= FAILURE_RATE <= 1.0
assert 0.0 <= UNAVAILABLE_FRACTION <= 1.0
assert AUDIT_LOG_MAX_ENTRIES > 0
