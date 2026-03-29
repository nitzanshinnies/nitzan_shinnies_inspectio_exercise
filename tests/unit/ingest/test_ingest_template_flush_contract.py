"""Ingest template A defers flush; worker batches flush before SQS delete (§18.3)."""

from __future__ import annotations

import pytest

from inspectio.ingest.ingest_consumer import append_ingest_template_a
from inspectio.ingest.schema import MessageIngestPayload, MessageIngestedV1
from inspectio.journal.writer import JournalWriter
from inspectio.settings import Settings


def _ingested(*, shard_id: int = 5) -> MessageIngestedV1:
    return MessageIngestedV1(
        message_id="m-ingest-flush-contract",
        payload=MessageIngestPayload(body="hello"),
        received_at_ms=1_700_000_000_000,
        shard_id=shard_id,
        idempotency_key="k-ingest-flush-contract",
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_append_ingest_template_a_does_not_call_flush_shard() -> None:
    """Batched flush at SQS batch boundary; template A must not PUT per message."""
    settings = Settings()
    writer = JournalWriter(settings, initial_hwm={5: -1})
    flushed: list[int] = []

    async def track_flush(shard_id: int) -> None:
        flushed.append(shard_id)

    writer.flush_shard = track_flush  # type: ignore[method-assign]

    await append_ingest_template_a(writer, _ingested(shard_id=5))
    assert flushed == []
