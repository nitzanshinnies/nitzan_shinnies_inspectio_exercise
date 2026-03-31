"""Transport-layer exceptions for persistence handoff (P12.2)."""

from __future__ import annotations


class PersistenceTransportBackpressureError(RuntimeError):
    """Raised when bounded in-flight capacity is exceeded in strict mode."""


class PersistenceTransportPublishError(RuntimeError):
    """Raised when retries are exhausted in strict mode."""
