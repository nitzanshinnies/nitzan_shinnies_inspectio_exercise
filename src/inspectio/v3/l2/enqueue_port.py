"""Injectable bulk enqueue (stub in P1; SQS in P2)."""

from __future__ import annotations

from typing import Protocol

from inspectio.v3.schemas.bulk_intent import BulkIntentV1


class BulkEnqueuePort(Protocol):
    def enqueue(self, bulk: BulkIntentV1) -> None:
        """Accept one logical bulk for downstream expander/SQS."""
