"""SQS consumer for persistence transport events (P12.3)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from inspectio.v3.persistence_transport.protocol import PersistenceTransportConsumer
from inspectio.v3.schemas.persistence_event import PersistenceEventV1


class SqsPersistenceTransportConsumer(PersistenceTransportConsumer):
    def __init__(
        self,
        *,
        client: Any,
        queue_url: str,
        wait_seconds: int,
        receive_max_events: int,
        ack_delete_max_concurrency: int = 6,
    ) -> None:
        self._client = client
        self._queue_url = queue_url
        self._wait_seconds = max(0, min(wait_seconds, 20))
        self._receive_max_events = max(1, min(10, receive_max_events))
        self._ack_delete_max_concurrency = max(1, min(8, ack_delete_max_concurrency))
        self._receipt_by_event_id: dict[str, str] = {}

    async def receive_many(self, *, max_events: int) -> list[PersistenceEventV1]:
        n = max(1, min(10, min(max_events, self._receive_max_events)))
        resp = await self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=n,
            WaitTimeSeconds=self._wait_seconds,
        )
        out: list[PersistenceEventV1] = []
        for msg in resp.get("Messages", []):
            event = PersistenceEventV1.model_validate_json(msg["Body"])
            self._receipt_by_event_id[event.event_id] = msg["ReceiptHandle"]
            out.append(event)
        return out

    async def ack_many(self, events: Sequence[PersistenceEventV1]) -> None:
        pending: list[tuple[str, str]] = []
        for event in events:
            rh = self._receipt_by_event_id.get(event.event_id)
            if rh is None:
                continue
            pending.append((event.event_id, rh))
        batched: list[tuple[dict[str, str], list[dict[str, str]]]] = []
        for chunk_start in range(0, len(pending), 10):
            chunk = pending[chunk_start : chunk_start + 10]
            id_to_event_id: dict[str, str] = {}
            entries: list[dict[str, str]] = []
            for idx, (event_id, receipt_handle) in enumerate(chunk):
                entry_id = str(idx)
                id_to_event_id[entry_id] = event_id
                entries.append({"Id": entry_id, "ReceiptHandle": receipt_handle})
            batched.append((id_to_event_id, entries))
        semaphore = asyncio.Semaphore(self._ack_delete_max_concurrency)

        async def _delete_batch(entries: list[dict[str, str]]) -> dict[str, Any]:
            async with semaphore:
                return await self._client.delete_message_batch(
                    QueueUrl=self._queue_url,
                    Entries=entries,
                )

        responses = await asyncio.gather(
            *[_delete_batch(entries) for _id_map, entries in batched]
        )
        had_failures = False
        for (id_to_event_id, _entries), resp in zip(batched, responses, strict=False):
            failed = resp.get("Failed", [])
            if failed:
                had_failures = True
            for ok in resp.get("Successful", []):
                event_id = id_to_event_id.get(ok["Id"])
                if event_id is None:
                    continue
                self._receipt_by_event_id.pop(event_id, None)
        if had_failures:
            raise RuntimeError("delete_message_batch failed for one or more entries")

    async def queue_oldest_age_ms(self) -> int | None:
        resp = await self._client.get_queue_attributes(
            QueueUrl=self._queue_url,
            AttributeNames=["ApproximateAgeOfOldestMessage"],
        )
        attrs = resp.get("Attributes", {})
        raw_seconds = attrs.get("ApproximateAgeOfOldestMessage")
        if raw_seconds is None:
            return None
        return max(0, int(raw_seconds) * 1000)
