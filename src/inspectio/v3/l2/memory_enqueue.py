"""In-memory bulk queue for unit tests and local dev (P1)."""

from __future__ import annotations

from inspectio.v3.schemas.bulk_intent import BulkIntentV1


class ListBulkEnqueue:
    def __init__(self) -> None:
        self.items: list[BulkIntentV1] = []

    def enqueue(self, bulk: BulkIntentV1) -> None:
        self.items.append(bulk)
