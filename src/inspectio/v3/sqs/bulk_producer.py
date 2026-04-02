"""Send BulkIntentV1 to the v3 bulk SQS queue (standard) using aioboto3."""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from inspectio.v3.schemas.bulk_intent import BulkIntentV1
from inspectio.v3.sqs.aws_throttle import is_aws_throttle_error
from inspectio.v3.sqs.backoff import compute_backoff_delay_ms


class SqsBulkEnqueue:
    """One SendMessage per bulk; shared Session reference per instance (P2).

    When ``bound_client`` is set (L2 app lifespan), ``enqueue`` reuses that client
    instead of opening a new context per request — required for high admission RPS.
    """

    def __init__(
        self,
        *,
        queue_url: str,
        region_name: str,
        endpoint_url: str | None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        max_attempts: int = 6,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
        rng: random.Random | None = None,
        session: aioboto3.Session | None = None,
        bound_client: Any | None = None,
    ) -> None:
        self._queue_url = queue_url
        self._region_name = region_name
        self._endpoint_url = endpoint_url
        self._access_key = aws_access_key_id
        self._secret_key = aws_secret_access_key
        self._max_attempts = max_attempts
        self._sleeper: Callable[[float], Awaitable[None]] = sleeper or asyncio.sleep
        self._rng = rng or random.Random()
        self._session = session or aioboto3.Session()
        self._bound_client = bound_client

    async def enqueue(self, bulk: BulkIntentV1) -> None:
        payload = json.dumps(
            bulk.model_dump(mode="json", by_alias=True, exclude_none=True),
        )
        if self._bound_client is not None:
            await self._send_payload_with_retries(self._bound_client, payload)
            return

        client_kw: dict[str, str] = {"region_name": self._region_name}
        if self._endpoint_url:
            client_kw["endpoint_url"] = self._endpoint_url
        if self._access_key:
            client_kw["aws_access_key_id"] = self._access_key
        if self._secret_key:
            client_kw["aws_secret_access_key"] = self._secret_key

        async with self._session.client("sqs", **client_kw) as client:
            await self._send_payload_with_retries(client, payload)

    async def _send_payload_with_retries(self, client: Any, payload: str) -> None:
        for attempt in range(self._max_attempts):
            try:
                await client.send_message(
                    QueueUrl=self._queue_url,
                    MessageBody=payload,
                )
                return
            except ClientError as exc:
                if not is_aws_throttle_error(exc) or attempt + 1 >= self._max_attempts:
                    raise
                delay_ms = compute_backoff_delay_ms(attempt, rng=self._rng)
                await self._sleeper(delay_ms / 1000.0)
