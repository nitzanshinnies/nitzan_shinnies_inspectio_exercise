"""BulkIntentV1 → N × SendUnitV1 (P3)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

from inspectio.v3.expander.sharding import shard_for_message_id
from inspectio.v3.schemas.bulk_intent import BulkIntentV1
from inspectio.v3.schemas.send_unit import SendUnitV1


def bulk_to_send_units(
    bulk: BulkIntentV1,
    *,
    shard_count: int,
    new_message_id: Callable[[], str] | None = None,
) -> list[SendUnitV1]:
    """Create ``count`` units sharing body and ``receivedAtMs`` from the bulk."""
    gen = new_message_id or (lambda: str(uuid.uuid4()))
    units: list[SendUnitV1] = []
    for _ in range(bulk.count):
        mid = gen()
        shard = shard_for_message_id(mid, shard_count)
        units.append(
            SendUnitV1(
                trace_id=bulk.trace_id,
                message_id=mid,
                body=bulk.body,
                received_at_ms=bulk.received_at_ms,
                batch_correlation_id=bulk.batch_correlation_id,
                shard=shard,
                attempts_completed=0,
            )
        )
    return units


def chunk_fixed_size(
    items: list[SendUnitV1], chunk_size: int
) -> Iterator[list[SendUnitV1]]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    for i in range(0, len(items), chunk_size):
        yield items[i : i + chunk_size]
