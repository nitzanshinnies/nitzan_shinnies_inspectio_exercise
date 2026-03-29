"""Construct L2 from environment (docker / local dev)."""

from __future__ import annotations

import os
import time

from fastapi import FastAPI

from inspectio.v3.l2.app import create_l2_app
from inspectio.v3.outcomes.null_store import NullOutcomesReader
from inspectio.v3.outcomes.redis_store import RedisOutcomesStore
from inspectio.v3.settings import build_sqs_bulk_enqueue_from_env


def create_l2_app_from_env() -> FastAPI:
    """SQS bulk enqueue + optional Redis outcomes (else empty GET lists)."""
    enqueue = build_sqs_bulk_enqueue_from_env()
    shard_count = int(os.environ.get("INSPECTIO_V3_SEND_SHARD_COUNT", "1"))
    redis_url = os.environ.get("INSPECTIO_REDIS_URL") or os.environ.get("REDIS_URL")
    outcomes_reader = (
        RedisOutcomesStore.from_url(redis_url) if redis_url else NullOutcomesReader()
    )
    return create_l2_app(
        enqueue_backend=enqueue,
        clock_ms=lambda: int(time.time() * 1000),
        shard_count=shard_count,
        outcomes_reader=outcomes_reader,
    )
