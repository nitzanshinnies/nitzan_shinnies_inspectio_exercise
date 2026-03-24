"""Redis Stream + staging keys: fast API accept, async batch flush to persistence/S3."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Sequence

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from inspectio_exercise.common.pending_stream_constants import (
    PENDING_STAGE_KEY_PREFIX,
    PENDING_STREAM_CONSUMER_GROUP,
    PENDING_STREAM_FIELD_BODY,
    PENDING_STREAM_FIELD_KEY,
    PENDING_STREAM_KEY,
)
from inspectio_exercise.notification.persistence_client import PersistenceHttpClient
from inspectio_exercise.persistence.object_write import ObjectWrite

logger = logging.getLogger(__name__)

_PENDING_STREAM_FLUSH_BATCH_MAX: int = max(
    1,
    int(os.environ.get("INSPECTIO_PENDING_STREAM_FLUSH_BATCH_MAX", "128")),
)
_PENDING_STREAM_BLOCK_MS: int = max(
    50, int(os.environ.get("INSPECTIO_PENDING_STREAM_BLOCK_MS", "2000"))
)
_PENDING_STAGE_TTL_SEC: int = max(
    60, int(os.environ.get("INSPECTIO_PENDING_STAGE_TTL_SEC", str(7 * 24 * 3600)))
)


def stage_key_for_pending(pending_key: str) -> str:
    return f"{PENDING_STAGE_KEY_PREFIX}{pending_key}"


async def ensure_pending_stream_group(redis: Redis) -> None:
    """Create the stream + consumer group if absent (idempotent)."""
    try:
        await redis.xgroup_create(
            name=PENDING_STREAM_KEY,
            groupname=PENDING_STREAM_CONSUMER_GROUP,
            id="0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def stage_pending_writes(redis: Redis, items: Sequence[ObjectWrite]) -> None:
    """Write staging keys and enqueue flush work (atomic per pipeline round)."""
    await stage_pending_writes_with_policy(redis, items, enqueue_for_flush=True)


async def stage_pending_writes_with_policy(
    redis: Redis,
    items: Sequence[ObjectWrite],
    *,
    enqueue_for_flush: bool,
) -> None:
    """Write staging keys; optionally enqueue stream entries for S3 flush."""
    materialized = list(items)
    if not materialized:
        return
    async with redis.pipeline(transaction=True) as pipe:
        for ow in materialized:
            pipe.set(stage_key_for_pending(ow.key), ow.body, ex=_PENDING_STAGE_TTL_SEC)
            if enqueue_for_flush:
                pipe.xadd(
                    PENDING_STREAM_KEY,
                    {
                        PENDING_STREAM_FIELD_KEY: ow.key.encode("utf-8"),
                        PENDING_STREAM_FIELD_BODY: ow.body,
                    },
                )
        await pipe.execute()


def _decode_field(fields: dict, name: bytes) -> bytes:
    if name in fields:
        v = fields[name]
        return v if isinstance(v, bytes) else str(v).encode("utf-8")
    str_name = name.decode("ascii")
    v = fields.get(str_name)
    if v is None:
        raise KeyError(str_name)
    return v if isinstance(v, bytes) else str(v).encode("utf-8")


async def run_pending_stream_flush_loop(
    redis: Redis,
    persistence: PersistenceHttpClient,
    stop: asyncio.Event,
) -> None:
    """XREADGROUP batches → ``put_objects`` → XACK → DEL staging keys."""
    consumer = f"flush-{socket.gethostname()}-{os.getpid()}"
    await ensure_pending_stream_group(redis)
    while not stop.is_set():
        try:
            resp = await redis.xreadgroup(
                groupname=PENDING_STREAM_CONSUMER_GROUP,
                consumername=consumer,
                streams={PENDING_STREAM_KEY: ">"},
                count=_PENDING_STREAM_FLUSH_BATCH_MAX,
                block=_PENDING_STREAM_BLOCK_MS if not stop.is_set() else 1,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pending stream flush xreadgroup failed")
            await asyncio.sleep(0.5)
            continue
        if not resp:
            continue
        for _stream_name, entries in resp:
            if not entries:
                continue
            msg_ids: list[str | bytes] = []
            writes: list[ObjectWrite] = []
            for msg_id, fields in entries:
                try:
                    pk_raw = _decode_field(fields, PENDING_STREAM_FIELD_KEY.encode("ascii"))
                    body = _decode_field(fields, PENDING_STREAM_FIELD_BODY.encode("ascii"))
                    pending_key = pk_raw.decode("utf-8")
                    writes.append(
                        ObjectWrite(key=pending_key, body=body, content_type="application/json")
                    )
                    msg_ids.append(msg_id)
                except (KeyError, UnicodeDecodeError, ValueError):
                    logger.warning("drop malformed pending stream entry id=%s", msg_id)
                    await redis.xack(PENDING_STREAM_KEY, PENDING_STREAM_CONSUMER_GROUP, msg_id)
            if not writes:
                continue
            try:
                await persistence.put_objects(writes)
            except Exception:
                logger.exception("pending stream flush put_objects failed; will retry via PEL")
                continue
            await redis.xack(PENDING_STREAM_KEY, PENDING_STREAM_CONSUMER_GROUP, *msg_ids)
            for ow in writes:
                await redis.delete(stage_key_for_pending(ow.key))


async def drain_pending_stream_once(
    redis: Redis,
    persistence: PersistenceHttpClient,
    *,
    max_rounds: int = 500,
) -> None:
    """Best-effort drain on shutdown (short block)."""
    consumer = f"drain-{os.getpid()}"
    await ensure_pending_stream_group(redis)
    for _ in range(max_rounds):
        resp = await redis.xreadgroup(
            groupname=PENDING_STREAM_CONSUMER_GROUP,
            consumername=consumer,
            streams={PENDING_STREAM_KEY: ">"},
            count=_PENDING_STREAM_FLUSH_BATCH_MAX,
            block=1,
        )
        if not resp or not resp[0][1]:
            break
        _stream_name, entries = resp[0]
        msg_ids = [e[0] for e in entries]
        writes: list[ObjectWrite] = []
        for _msg_id, fields in entries:
            pk_raw = _decode_field(fields, PENDING_STREAM_FIELD_KEY.encode("ascii"))
            body = _decode_field(fields, PENDING_STREAM_FIELD_BODY.encode("ascii"))
            writes.append(
                ObjectWrite(
                    key=pk_raw.decode("utf-8"),
                    body=body,
                    content_type="application/json",
                )
            )
        if writes:
            await persistence.put_objects(writes)
            await redis.xack(PENDING_STREAM_KEY, PENDING_STREAM_CONSUMER_GROUP, *msg_ids)
            for ow in writes:
                await redis.delete(stage_key_for_pending(ow.key))
