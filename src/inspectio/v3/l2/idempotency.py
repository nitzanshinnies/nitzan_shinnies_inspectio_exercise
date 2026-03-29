"""In-process idempotency for L2 (P1); multi-replica gap until Redis (master plan §4.2)."""

from __future__ import annotations

from collections.abc import Callable


class IdempotencyConflictError(Exception):
    """Same Idempotency-Key with a different payload."""


class InMemoryIdempotencyStore:
    """TTL-bounded map: key → (batch_correlation_id, request_fingerprint, expires_at_ms)."""

    def __init__(self, *, ttl_ms: int, clock_ms: Callable[[], int]) -> None:
        self._clock_ms = clock_ms
        self._entries: dict[str, tuple[str, str, int]] = {}
        self._ttl_ms = ttl_ms

    def resolve(
        self, key: str, fingerprint: str, new_batch_id: str
    ) -> tuple[str, bool]:
        """Return (batch_correlation_id, is_duplicate). Duplicate skips enqueue."""
        now = self._clock_ms()
        self._purge_expired(now)
        existing = self._entries.get(key)
        if existing is not None:
            batch_id, fp, expires_at_ms = existing
            if expires_at_ms >= now:
                if fp != fingerprint:
                    raise IdempotencyConflictError
                return batch_id, True
            del self._entries[key]
        self._entries[key] = (new_batch_id, fingerprint, now + self._ttl_ms)
        return new_batch_id, False

    def _purge_expired(self, now: int) -> None:
        expired = [k for k, (_, _, exp) in self._entries.items() if exp < now]
        for k in expired:
            del self._entries[k]
