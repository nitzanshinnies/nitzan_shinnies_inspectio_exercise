"""Expander process entrypoint (long-poll bulk SQS → sharded send queues)."""

from __future__ import annotations

import asyncio
import logging
import random

import aioboto3

from inspectio.v3.expander.consumer import receive_and_expand_once
from inspectio.v3.expander.dedupe import ExpandedBulkDedupe
from inspectio.v3.expander.metrics import ExpansionMetrics
from inspectio.v3.settings import (
    V3ExpanderSettings,
    sqs_client_kwargs_from_expander_settings,
)


async def amain() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = V3ExpanderSettings()
    session = aioboto3.Session()
    dedupe = ExpandedBulkDedupe()
    metrics = ExpansionMetrics()
    rng = random.Random()
    client_kw = sqs_client_kwargs_from_expander_settings(settings)
    sleeper = asyncio.sleep
    while True:
        async with session.client("sqs", **client_kw) as client:
            await receive_and_expand_once(
                client,
                bulk_queue_url=settings.bulk_queue_url,
                wait_seconds=settings.receive_wait_seconds,
                visibility_timeout_seconds=settings.bulk_visibility_timeout_seconds,
                dedupe=dedupe,
                send_queue_urls=settings.send_queue_urls,
                metrics=metrics,
                sleeper=sleeper,
                rng=rng,
            )


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
