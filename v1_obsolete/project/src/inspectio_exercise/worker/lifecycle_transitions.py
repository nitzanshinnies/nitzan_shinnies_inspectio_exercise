"""Pending → terminal success/failed and reconciliation (CORE_LIFECYCLE.md)."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from inspectio_exercise.domain.retry import (
    BRIEF_REASON_TERMINAL_AFTER_SIX_FAILURES,
    attempt_count_is_terminal,
    next_due_at_ms_after_failure,
)
from inspectio_exercise.domain.sharding import shard_id_for_message
from inspectio_exercise.domain.utc_paths import terminal_failed_key, terminal_success_key
from inspectio_exercise.worker import clocks
from inspectio_exercise.worker.outcome_notifier import OutcomeNotifier
from inspectio_exercise.worker.retrying_persistence import RetryingPersistence
from inspectio_exercise.worker.terminal_scanner import TerminalScanner

logger = logging.getLogger(__name__)


class LifecycleTransitions:
    """Terminal writes + notification publish; uses scheduler lock for in-memory state."""

    def __init__(
        self,
        *,
        delete_pending_best_effort: Callable[[str], Awaitable[None]],
        drop_locked: Callable[[str], None],
        lock: asyncio.Lock,
        outcomes: OutcomeNotifier,
        persist: RetryingPersistence,
        records: dict[str, dict[str, Any]],
        schedule_locked: Callable[[str, int], None],
        scanner: TerminalScanner,
        total_shards: int,
    ) -> None:
        self._delete_pending_best_effort = delete_pending_best_effort
        self._drop_locked = drop_locked
        self._lock = lock
        self._outcomes = outcomes
        self._persist = persist
        self._records = records
        self._schedule_locked = schedule_locked
        self._scanner = scanner
        self._total_shards = total_shards

    async def reconcile_from_terminal(
        self,
        mid: str,
        pending_key: str,
        *,
        body: dict[str, Any],
        outcome: str,
        terminal_key: str,
    ) -> None:
        shard_id = shard_id_for_message(mid, self._total_shards)
        recorded_at = int(body.get("recordedAt", clocks.now_ms()))
        logger.info(
            "reconciling stale pending from existing terminal message_id=%s outcome=%s",
            mid,
            outcome,
        )
        await self._delete_pending_best_effort(pending_key)
        try:
            ac_pub = int(body.get("attemptCount", 0))
        except (TypeError, ValueError):
            ac_pub = 0
        reason_pub = body.get("reason") if outcome == "failed" else None
        if not isinstance(reason_pub, str):
            reason_pub = None
        await self._outcomes.publish(
            message_id=mid,
            outcome=outcome,
            recorded_at=recorded_at,
            shard_id=shard_id,
            attempt_count=ac_pub,
            brief_reason=reason_pub,
            terminal_storage_key=terminal_key,
        )
        async with self._lock:
            self._drop_locked(mid)

    async def transition_failure(self, mid: str, rec: dict[str, Any], pending_key: str) -> None:
        now_ms = clocks.now_ms()
        probe = await self._scanner.find_existing(mid, now_ms)
        if probe is not None:
            outcome, terminal_key, body = probe
            await self.reconcile_from_terminal(
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
            recorded_at = clocks.now_ms()
            record_out = {
                **rec,
                "attemptCount": new_ac,
                "recordedAt": recorded_at,
                "status": "failed",
            }
            terminal_key = terminal_failed_key(mid, recorded_at)
            raw = json.dumps(record_out, separators=(",", ":")).encode("utf-8")
            await self._persist.put_object(terminal_key, raw)
            await self._delete_pending_best_effort(pending_key)
            await self._outcomes.publish(
                message_id=mid,
                outcome="failed",
                recorded_at=recorded_at,
                shard_id=shard_id,
                attempt_count=new_ac,
                brief_reason=BRIEF_REASON_TERMINAL_AFTER_SIX_FAILURES,
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
        await self._persist.put_object(pending_key, raw)
        async with self._lock:
            if mid not in self._records:
                return
            self._records[mid] = updated
            self._schedule_locked(mid, nd)

    async def transition_success(self, mid: str, rec: dict[str, Any], pending_key: str) -> None:
        recorded_at = clocks.now_ms()
        probe = await self._scanner.find_existing(mid, recorded_at)
        if probe is not None:
            outcome, terminal_key, body = probe
            if outcome == "success":
                await self.reconcile_from_terminal(
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
        await self._persist.put_object(terminal_key, raw)
        await self._delete_pending_best_effort(pending_key)
        await self._outcomes.publish(
            message_id=mid,
            outcome="success",
            recorded_at=recorded_at,
            shard_id=shard_id,
            attempt_count=int(rec["attemptCount"]),
            brief_reason=None,
            terminal_storage_key=terminal_key,
        )
        async with self._lock:
            self._drop_locked(mid)
