"""SQS consumer for persistence transport events (P12.3)."""

from __future__ import annotations

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
    ) -> None:
        self._client = client
        self._queue_url = queue_url
        self._wait_seconds = max(0, min(wait_seconds, 20))
        self._receive_max_events = max(1, min(10, receive_max_events))
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
        for event in events:
            rh = self._receipt_by_event_id.pop(event.event_id, None)
            if rh is None:
                continue
            await self._client.delete_message(
                QueueUrl=self._queue_url,
                ReceiptHandle=rh,
            )

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
