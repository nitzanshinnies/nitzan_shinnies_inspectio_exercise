"""SQS FIFO long-poll consumer ."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aioboto3

from inspectio.settings import Settings


@dataclass(frozen=True, slots=True)
class RawSqsMessage:
    """One FIFO queue message with receipt handle for delete."""

    body: str
    receipt_handle: str


class SqsFifoBatchFetcher:
    """Long-poll `ReceiveMessage` for the ingest FIFO queue."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = aioboto3.Session()
        self._sqs_client_ctx: Any | None = None
        self._sqs_client: Any | None = None

    def _client_kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {"region_name": self._settings.aws_region}
        if self._settings.aws_endpoint_url:
            kw["endpoint_url"] = self._settings.aws_endpoint_url
        return kw

    async def start(self) -> None:
        if self._sqs_client is not None:
            return
        self._sqs_client_ctx = self._session.client("sqs", **self._client_kwargs())
        self._sqs_client = await self._sqs_client_ctx.__aenter__()

    async def stop(self) -> None:
        if self._sqs_client_ctx is None:
            return
        await self._sqs_client_ctx.__aexit__(None, None, None)
        self._sqs_client_ctx = None
        self._sqs_client = None

    async def receive_messages(
        self,
        *,
        max_messages: int = 10,
        wait_seconds: int = 20,
    ) -> list[RawSqsMessage]:
        queue_url = self._settings.ingest_queue_url.strip()
        if not queue_url:
            msg = "INSPECTIO_INGEST_QUEUE_URL must be set"
            raise RuntimeError(msg)
        cap = min(max(1, max_messages), 10)
        await self.start()
        assert self._sqs_client is not None
        resp = await self._sqs_client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=cap,
            WaitTimeSeconds=min(max(0, wait_seconds), 20),
            AttributeNames=["All"],
            MessageAttributeNames=["All"],
        )
        out: list[RawSqsMessage] = []
        for row in resp.get("Messages", []) or []:
            body = row.get("Body")
            handle = row.get("ReceiptHandle")
            if body is None or handle is None:
                continue
            out.append(RawSqsMessage(body=str(body), receipt_handle=str(handle)))
        return out

    async def delete_message(self, receipt_handle: str) -> None:
        queue_url = self._settings.ingest_queue_url.strip()
        await self.start()
        assert self._sqs_client is not None
        await self._sqs_client.delete_message(
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
        )

    async def delete_messages_batch(self, receipt_handles: list[str]) -> None:
        """Delete up to 10 messages with one SQS API call."""
        if not receipt_handles:
            return
        queue_url = self._settings.ingest_queue_url.strip()
        await self.start()
        assert self._sqs_client is not None
        chunk = receipt_handles[:10]
        entries = [
            {
                "Id": str(i),
                "ReceiptHandle": handle,
            }
            for i, handle in enumerate(chunk)
        ]
        resp = await self._sqs_client.delete_message_batch(
            QueueUrl=queue_url,
            Entries=entries,
        )
        failed = resp.get("Failed", []) or []
        if failed:
            for row in failed:
                idx = int(row["Id"])
                await self.delete_message(chunk[idx])
