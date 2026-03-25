"""Module-level behavior constants per plans/MOCK_SMS.md §5.

Defaults match the exercise spec; optional env overrides support large-scale
local runs (audit window / ring buffer / failure rate) without editing code.
"""

from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(str(raw).strip())


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    return float(str(raw).strip())


def _env_int_or_none(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return None
    return int(str(raw).strip())


AUDIT_LOG_MAX_ENTRIES: int = _env_int("INSPECTIO_MOCK_AUDIT_LOG_MAX_ENTRIES", 100_000)
AUDIT_SENDS_DEFAULT_LIMIT: int = _env_int("INSPECTIO_MOCK_AUDIT_SENDS_DEFAULT_LIMIT", 100)
AUDIT_SENDS_MAX_LIMIT: int = _env_int("INSPECTIO_MOCK_AUDIT_SENDS_MAX_LIMIT", 1000)
AUDIT_REDACT_TO: bool = True
EXPOSE_AUDIT_ENDPOINT: bool = True
FAILURE_RATE: float = _env_float("INSPECTIO_MOCK_FAILURE_RATE", 0.2)
LATENCY_MS: int = _env_int("INSPECTIO_MOCK_LATENCY_MS", 0)
LISTEN_PORT: int = _env_int("INSPECTIO_MOCK_SMS_PORT", 8080)
RNG_SEED: int | None = _env_int_or_none("INSPECTIO_MOCK_RNG_SEED")
UNAVAILABLE_FRACTION: float = _env_float("INSPECTIO_MOCK_UNAVAILABLE_FRACTION", 0.5)

# Flip to True when mock SMS + worker contract tests pass (plans/TESTS.md §4.6).
MOCK_SMS_CONTRACT_COMPLETE: bool = True

assert 0.0 <= FAILURE_RATE <= 1.0
assert 0.0 <= UNAVAILABLE_FRACTION <= 1.0
assert AUDIT_LOG_MAX_ENTRIES > 0
assert AUDIT_SENDS_DEFAULT_LIMIT >= 1
assert AUDIT_SENDS_MAX_LIMIT >= AUDIT_SENDS_DEFAULT_LIMIT
