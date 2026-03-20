"""Module-level behavior constants per plans/MOCK_SMS.md §5 (no env tuning)."""

from __future__ import annotations

AUDIT_LOG_MAX_ENTRIES: int = 100_000
AUDIT_REDACT_TO: bool = True
EXPOSE_AUDIT_ENDPOINT: bool = True
FAILURE_RATE: float = 0.2
LATENCY_MS: int = 0
LISTEN_PORT: int = 8080
RNG_SEED: int | None = None
UNAVAILABLE_FRACTION: float = 0.5

# Flip to True when mock SMS + worker contract tests pass (plans/TESTS.md §4.6).
MOCK_SMS_CONTRACT_COMPLETE: bool = False

assert 0.0 <= FAILURE_RATE <= 1.0
assert 0.0 <= UNAVAILABLE_FRACTION <= 1.0
assert AUDIT_LOG_MAX_ENTRIES > 0
