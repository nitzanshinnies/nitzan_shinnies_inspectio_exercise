"""Shard-scoped scheduler: discover pending, due selection, SMS send, terminal writes (plans/CORE_LIFECYCLE.md).

Environment variables and operational tradeoffs (lookback, invalid payload): see README.md **Worker env**.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import json
import logging
import time
import uuid
from typing import Any, Protocol

import httpx

from inspectio_exercise.domain.retry import attempt_count_is_terminal, next_due_at_ms_after_failure
from inspectio_exercise.domain.sharding import (
    owned_shard_ids,
    pending_prefix_for_shard,
    pod_index_from_hostname,
    shard_id_for_message,
)
from inspectio_exercise.domain.sms_outcome import is_successful_send
from inspectio_exercise.domain.utc_paths import terminal_failed_key, terminal_success_key
from inspectio_exercise.worker.config import (
    NOTIFICATION_PUBLISH_BASE_DELAY_SEC,
    NOTIFICATION_PUBLISH_MAX_ATTEMPTS,
    OUTCOMES_HTTP_PATH,
    PERSISTENCE_READ_BASE_DELAY_SEC,
    PERSISTENCE_READ_MAX_ATTEMPTS,
    TERMINAL_LOOKBACK_HOURS,
    WORKER_TICK_INTERVAL_SEC,
    WorkerSettings,
)
from inspectio_exercise.worker.persistence_retry import run_with_persistence_retries
from inspectio_exercise.worker.terminal_lookup import (
    key_matches_message_terminal,
    terminal_prefixes_for_lookback,
)

logger = logging.getLogger(__name__)


class PersistenceAsyncPort(Protocol):
    async def delete_object(self, key: str) -> None: ...

    async def get_object(self, key: str) -> bytes: ...

    async def list_prefix(
        self, prefix: str, max_keys: int | None = None
    ) -> list[dict[str, Any]]: ...

    async def put_object(self, key: str, body: bytes, content_type: str = ...) -> None: ...


def _now_ms() -> int:
    return int(time.time() * 1000)


def is_valid_pending_row(message_id: str, data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("messageId") != message_id:
        return False
    if data.get("status") != "pending":
        return False
    ac = data.get("attemptCount")
    if not isinstance(ac, int) or ac < 0 or ac > 6:
        return False
    nd = data.get("nextDueAt")
    if not isinstance(nd, int):
        return False
    pl = data.get("payload")
    if not isinstance(pl, dict):
        return False
    return isinstance(pl.get("to"), str) and isinstance(pl.get("body"), str)


def message_id_from_pending_key(key: str) -> str | None:
    base = key.rsplit("/", maxsplit=1)[-1]
    if not base.endswith(".json") or len(base) < 6:
        return None
    return base[:-5]


async def post_mock_send(
    client: httpx.AsyncClient,
    *,
    attempt_index: int,
    body: str,
    message_id: str,
    to: str,
) -> int:
    response = await client.post(
        "/send",
        json={
            "to": to,
            "body": body,
            "messageId": message_id,
            "attemptIndex": attempt_index,
        },
    )
    return response.status_code


class WorkerRuntime:
    """Owned-shard pending discovery, min-heap due selection, concurrent sends per tick."""

    def __init__(
        self,
        *,
        notify_client: httpx.AsyncClient,
        persistence: PersistenceAsyncPort,
        persistence_read_backoff_sec: float | None = None,
        persistence_read_max_attempts: int | None = None,
        settings: WorkerSettings,
        sms_client: httpx.AsyncClient,
        terminal_lookback_hours: int | None = None,
        tick_interval_sec: float | None = None,
    ) -> None:
        self._notify = notify_client
        self._persistence = persistence
        self._settings = settings
        self._sms = sms_client
        self._tick_interval = (
            tick_interval_sec if tick_interval_sec is not None else WORKER_TICK_INTERVAL_SEC
        )
        self._persist_attempts = (
            persistence_read_max_attempts
            if persistence_read_max_attempts is not None
            else PERSISTENCE_READ_MAX_ATTEMPTS
        )
        self._persist_backoff = (
            persistence_read_backoff_sec
            if persistence_read_backoff_sec is not None
            else PERSISTENCE_READ_BASE_DELAY_SEC
        )
        self._terminal_lookback = (
            terminal_lookback_hours
            if terminal_lookback_hours is not None
            else TERMINAL_LOOKBACK_HOURS
        )
        pod_idx = pod_index_from_hostname(settings.hostname)
        self._owned = owned_shard_ids(pod_idx, settings.shards_per_pod, settings.total_shards)
        self._total_shards = settings.total_shards
        self._heap: list[tuple[int, int, str]] = []
        self._seq = 0
        self._records: dict[str, dict[str, Any]] = {}
        self._pending_keys: dict[str, str] = {}
        self._lock = asyncio.Lock()

    def _drop_locked(self, mid: str) -> None:
        self._records.pop(mid, None)
        self._pending_keys.pop(mid, None)

    def _schedule_locked(self, mid: str, due_ms: int) -> None:
        self._seq += 1
        heapq.heappush(self._heap, (due_ms, self._seq, mid))

    async def _collect_due(self, now_ms: int) -> list[tuple[str, dict[str, Any], str]]:
        async with self._lock:
            out: list[tuple[str, dict[str, Any], str]] = []
            while self._heap and self._heap[0][0] <= now_ms:
                due_ms, _, mid = heapq.heappop(self._heap)
                rec = self._records.get(mid)
                if rec is None:
                    continue
                key = self._pending_keys.get(mid)
                if key is None:
                    continue
                if int(rec["nextDueAt"]) != due_ms:
                    continue
                out.append((mid, rec, key))
            return out

    async def _delete_pending_best_effort(self, pending_key: str) -> None:
        with contextlib.suppress(KeyError):
            await self._persistence_delete_with_retries(pending_key)

    async def _discover(self) -> None:
        for shard in self._owned:
            prefix = pending_prefix_for_shard(shard)
            try:
                rows = await self._persistence_list_prefix_with_retries(prefix)
            except Exception:
                logger.exception("list_prefix failed prefix=%s after retries", prefix)
                continue
            for row in rows:
                key = row["Key"]
                mid = message_id_from_pending_key(key)
                if mid is None:
                    continue
                async with self._lock:
                    known = mid in self._records
                if known:
                    continue
                try:
                    raw = await self._persistence_get_with_retries(key)
                except KeyError:
                    continue
                except Exception:
                    logger.exception("get_object failed key=%s after retries", key)
                    continue
                await self._ingest_if_new(mid, key, raw)

    async def _find_existing_terminal_record(
        self, message_id: str, now_ms: int
    ) -> tuple[str, str, dict[str, Any]] | None:
        for tree_root, outcome in (("state/success", "success"), ("state/failed", "failed")):
            for scan_prefix in terminal_prefixes_for_lookback(
                lookback_hours=self._terminal_lookback,
                now_ms=now_ms,
                tree_root=tree_root,
            ):
                try:
                    rows = await self._persistence_list_prefix_with_retries(scan_prefix)
                except Exception:
                    logger.exception("terminal scan list_prefix failed prefix=%s", scan_prefix)
                    continue
                for row in rows:
                    tkey = row["Key"]
                    if not key_matches_message_terminal(tkey, message_id):
                        continue
                    try:
                        raw = await self._persistence_get_with_retries(tkey)
                    except KeyError:
                        continue
                    except Exception:
                        logger.exception("terminal scan get_object failed key=%s", tkey)
                        continue
                    try:
                        data = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(data, dict):
                        continue
                    if data.get("messageId") != message_id:
                        continue
                    if data.get("status") != outcome:
                        continue
                    return outcome, tkey, data
        return None

    async def _handle_one(self, mid: str, rec: dict[str, Any], pending_key: str) -> None:
        try:
            await self._persistence_get_with_retries(pending_key)
        except KeyError:
            async with self._lock:
                self._drop_locked(mid)
            return
        now_ms = _now_ms()
        existing = await self._find_existing_terminal_record(mid, now_ms)
        if existing is not None:
            outcome, terminal_key, body = existing
            await self._reconcile_from_terminal(
                mid,
                pending_key,
                body=body,
                outcome=outcome,
                terminal_key=terminal_key,
            )
            return
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        to = payload.get("to", "")
        body = payload.get("body", "")
        if not isinstance(to, str) or not isinstance(body, str):
            logger.warning(
                "invalid payload for message_id=%s — removing pending object and dropping scheduler state",
                mid,
            )
            await self._delete_pending_best_effort(pending_key)
            async with self._lock:
                self._drop_locked(mid)
            return
        ac = int(rec["attemptCount"])
        status = await post_mock_send(
            self._sms,
            to=to,
            body=body,
            message_id=mid,
            attempt_index=ac,
        )
        if is_successful_send(status):
            await self._transition_success(mid, rec, pending_key)
        else:
            await self._transition_failure(mid, rec, pending_key)

    async def _ingest_if_new(self, mid: str, key: str, raw: bytes) -> None:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("skipping non-JSON pending object key=%s", key)
            return
        if not is_valid_pending_row(mid, data):
            logger.warning("skipping invalid pending record key=%s", key)
            return
        async with self._lock:
            if mid in self._records:
                return
            self._records[mid] = data
            self._pending_keys[mid] = key
            self._schedule_locked(mid, int(data["nextDueAt"]))

    async def _persistence_delete_with_retries(self, key: str) -> None:
        async def call() -> None:
            await self._persistence.delete_object(key)

        await run_with_persistence_retries(
            f"delete_object:{key!r}",
            call,
            max_attempts=self._persist_attempts,
            base_delay_sec=self._persist_backoff,
        )

    async def _persistence_get_with_retries(self, key: str) -> bytes:
        async def call() -> bytes:
            return await self._persistence.get_object(key)

        return await run_with_persistence_retries(
            f"get_object:{key!r}",
            call,
            max_attempts=self._persist_attempts,
            base_delay_sec=self._persist_backoff,
        )

    async def _persistence_list_prefix_with_retries(self, prefix: str) -> list[dict[str, Any]]:
        async def call() -> list[dict[str, Any]]:
            return await self._persistence.list_prefix(prefix)

        return await run_with_persistence_retries(
            f"list_prefix:{prefix!r}",
            call,
            max_attempts=self._persist_attempts,
            base_delay_sec=self._persist_backoff,
        )

    async def _persistence_put_with_retries(self, key: str, raw: bytes) -> None:
        async def call() -> None:
            await self._persistence.put_object(key, raw)

        await run_with_persistence_retries(
            f"put_object:{key!r}",
            call,
            max_attempts=self._persist_attempts,
            base_delay_sec=self._persist_backoff,
        )

    async def _post_outcome_notification(
        self,
        *,
        message_id: str,
        outcome: str,
        recorded_at: int,
        shard_id: int,
        terminal_storage_key: str | None = None,
    ) -> None:
        if terminal_storage_key is not None:
            notification_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{terminal_storage_key}\n{outcome}")
            )
        else:
            notification_id = str(uuid.uuid4())
        body = {
            "messageId": message_id,
            "notificationId": notification_id,
            "outcome": outcome,
            "recordedAt": recorded_at,
            "shardId": shard_id,
        }
        last_exc: httpx.HTTPError | None = None
        for try_idx in range(NOTIFICATION_PUBLISH_MAX_ATTEMPTS):
            try:
                response = await self._notify.post(OUTCOMES_HTTP_PATH, json=body)
                response.raise_for_status()
                return
            except httpx.HTTPError as exc:
                last_exc = exc
                if try_idx + 1 >= NOTIFICATION_PUBLISH_MAX_ATTEMPTS:
                    break
                delay = NOTIFICATION_PUBLISH_BASE_DELAY_SEC * (2**try_idx)
                await asyncio.sleep(delay)
        assert last_exc is not None
        logger.error(
            "notification publish exhausted attempts message_id=%s",
            message_id,
            exc_info=last_exc,
        )
        raise last_exc

    async def _reconcile_from_terminal(
        self,
        mid: str,
        pending_key: str,
        *,
        body: dict[str, Any],
        outcome: str,
        terminal_key: str,
    ) -> None:
        shard_id = shard_id_for_message(mid, self._total_shards)
        recorded_at = int(body.get("recordedAt", _now_ms()))
        logger.info(
            "reconciling stale pending from existing terminal message_id=%s outcome=%s",
            mid,
            outcome,
        )
        await self._delete_pending_best_effort(pending_key)
        await self._post_outcome_notification(
            message_id=mid,
            outcome=outcome,
            recorded_at=recorded_at,
            shard_id=shard_id,
            terminal_storage_key=terminal_key,
        )
        async with self._lock:
            self._drop_locked(mid)

    async def _transition_failure(self, mid: str, rec: dict[str, Any], pending_key: str) -> None:
        now_ms = _now_ms()
        probe = await self._find_existing_terminal_record(mid, now_ms)
        if probe is not None:
            outcome, terminal_key, body = probe
            await self._reconcile_from_terminal(
                mid,
                pending_key,
                body=body,
                outcome=outcome,
                terminal_key=terminal_key,
            )
            return

        ac = int(rec["attemptCount"])
        new_ac = ac + 1
        shard_id = shard_id_for_message(mid, self._total_shards)
        if attempt_count_is_terminal(new_ac):
            recorded_at = _now_ms()
            record_out = {
                **rec,
                "attemptCount": new_ac,
                "recordedAt": recorded_at,
                "status": "failed",
            }
            terminal_key = terminal_failed_key(mid, recorded_at)
            raw = json.dumps(record_out, separators=(",", ":")).encode("utf-8")
            await self._persistence_put_with_retries(terminal_key, raw)
            await self._delete_pending_best_effort(pending_key)
            await self._post_outcome_notification(
                message_id=mid,
                outcome="failed",
                recorded_at=recorded_at,
                shard_id=shard_id,
                terminal_storage_key=terminal_key,
            )
            async with self._lock:
                self._drop_locked(mid)
            return

        nd = next_due_at_ms_after_failure(now_ms, ac)
        if nd is None:
            logger.error("unexpected missing retry delay message_id=%s ac=%s", mid, ac)
            return
        updated = {**rec, "attemptCount": new_ac, "nextDueAt": nd}
        raw = json.dumps(updated, separators=(",", ":")).encode("utf-8")
        await self._persistence_put_with_retries(pending_key, raw)
        async with self._lock:
            if mid not in self._records:
                return
            self._records[mid] = updated
            self._schedule_locked(mid, nd)

    async def _transition_success(self, mid: str, rec: dict[str, Any], pending_key: str) -> None:
        recorded_at = _now_ms()
        probe = await self._find_existing_terminal_record(mid, recorded_at)
        if probe is not None:
            outcome, terminal_key, body = probe
            if outcome == "success":
                await self._reconcile_from_terminal(
                    mid,
                    pending_key,
                    body=body,
                    outcome="success",
                    terminal_key=terminal_key,
                )
                return
            logger.warning(
                "success transition but failed terminal exists message_id=%s — dropping pending",
                mid,
            )
            await self._delete_pending_best_effort(pending_key)
            async with self._lock:
                self._drop_locked(mid)
            return

        shard_id = shard_id_for_message(mid, self._total_shards)
        terminal_key = terminal_success_key(mid, recorded_at)
        record_out = {
            **rec,
            "recordedAt": recorded_at,
            "status": "success",
        }
        raw = json.dumps(record_out, separators=(",", ":")).encode("utf-8")
        await self._persistence_put_with_retries(terminal_key, raw)
        await self._delete_pending_best_effort(pending_key)
        await self._post_outcome_notification(
            message_id=mid,
            outcome="success",
            recorded_at=recorded_at,
            shard_id=shard_id,
            terminal_storage_key=terminal_key,
        )
        async with self._lock:
            self._drop_locked(mid)

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            t0 = time.monotonic()
            try:
                await self.run_tick()
            except Exception:
                logger.exception("worker tick failed")
            elapsed = time.monotonic() - t0
            sleep_for = max(0.0, self._tick_interval - elapsed)
            if sleep_for <= 0:
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=sleep_for)

    async def run_tick(self) -> None:
        now_ms = _now_ms()
        await self._discover()
        due = await self._collect_due(now_ms)
        if not due:
            return
        await asyncio.gather(*(self._handle_one(mid, dict(rec), key) for mid, rec, key in due))
