"""Checkpoint + segment replay bootstrap for worker recovery (P12.4)."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass

from inspectio.v3.domain.retry_schedule import attempt_deadline_ms
from inspectio.v3.persistence_recovery.order import sorted_for_replay
from inspectio.v3.persistence_recovery.reducer import ReplayedMessageState, fold_event
from inspectio.v3.persistence_writer.object_store import PersistenceObjectStore
from inspectio.v3.schemas.persistence_checkpoint import PersistenceCheckpointV1
from inspectio.v3.schemas.persistence_event import PersistenceEventV1


def _checkpoint_key(*, shard: int) -> str:
    return f"state/checkpoints/{shard}/latest.json"


def _segment_prefix(*, shard: int) -> str:
    return f"state/events/{shard}/"


@dataclass(slots=True)
class RecoveryPendingSendUnit:
    message_id: str
    body: str
    received_at_ms: int
    batch_correlation_id: str
    trace_id: str
    shard: int
    attempt_count: int
    next_due_at_ms: int | None


@dataclass(slots=True)
class RecoverySnapshot:
    pending_units: list[RecoveryPendingSendUnit]
    terminal_message_ids: set[str]
    loaded_segments: int
    loaded_events: int
    skipped_events_checkpoint_watermark: int
    skipped_pending_missing_body: int
    skipped_pending_invalid_timing: int


class PersistenceRecoveryBootstrap:
    """Rebuild in-memory scheduler state from durable writer segments."""

    def __init__(
        self, *, object_store: PersistenceObjectStore, shard_ids: list[int]
    ) -> None:
        self._store = object_store
        self._shard_ids = shard_ids

    async def recover(self) -> RecoverySnapshot:
        states: dict[str, ReplayedMessageState] = {}
        loaded_segments = 0
        loaded_events = 0
        skipped_events_checkpoint_watermark = 0

        for shard in self._shard_ids:
            checkpoint = await self._load_checkpoint(shard=shard)
            watermark = self._checkpoint_watermark(checkpoint=checkpoint)
            for key in await self._segment_keys(shard=shard, checkpoint=checkpoint):
                loaded_segments += 1
                segment_events = await self._read_segment_events(key=key)
                loaded_events += len(segment_events)
                ordered_events = sorted_for_replay(segment_events)
                replay_events = self._events_after_watermark(
                    events=ordered_events,
                    watermark=watermark,
                )
                skipped_events_checkpoint_watermark += len(ordered_events) - len(
                    replay_events
                )
                for event in replay_events:
                    current = states.get(event.message_id or "")
                    next_state = fold_event(current, event)
                    if event.message_id is not None and next_state is not None:
                        states[event.message_id] = next_state

        pending_units: list[RecoveryPendingSendUnit] = []
        terminal_message_ids: set[str] = set()
        skipped_pending_missing_body = 0
        skipped_pending_invalid_timing = 0

        for state in states.values():
            if state.status in {"success", "failed"}:
                terminal_message_ids.add(state.message_id)
                continue
            if not state.body:
                skipped_pending_missing_body += 1
                continue
            if not self._is_valid_pending_timing(state=state):
                skipped_pending_invalid_timing += 1
                continue
            pending_units.append(
                RecoveryPendingSendUnit(
                    message_id=state.message_id,
                    body=state.body,
                    received_at_ms=state.received_at_ms,
                    batch_correlation_id=state.batch_correlation_id,
                    trace_id=state.trace_id,
                    shard=state.shard,
                    attempt_count=state.attempt_count,
                    next_due_at_ms=state.next_due_at_ms,
                )
            )

        pending_units.sort(key=lambda unit: (unit.received_at_ms, unit.message_id))
        return RecoverySnapshot(
            pending_units=pending_units,
            terminal_message_ids=terminal_message_ids,
            loaded_segments=loaded_segments,
            loaded_events=loaded_events,
            skipped_events_checkpoint_watermark=skipped_events_checkpoint_watermark,
            skipped_pending_missing_body=skipped_pending_missing_body,
            skipped_pending_invalid_timing=skipped_pending_invalid_timing,
        )

    async def _load_checkpoint(self, *, shard: int) -> PersistenceCheckpointV1 | None:
        payload = await self._store.get_json(key=_checkpoint_key(shard=shard))
        if payload is None:
            return None
        return PersistenceCheckpointV1.model_validate(payload)

    async def _segment_keys(
        self,
        *,
        shard: int,
        checkpoint: PersistenceCheckpointV1 | None,
    ) -> list[str]:
        prefix = _segment_prefix(shard=shard)
        keys = sorted(await self._store.list_keys(prefix=prefix))
        if checkpoint is None:
            return keys
        watermark = self._checkpoint_watermark(checkpoint=checkpoint)
        if watermark is None:
            return keys
        min_segment_seq = watermark[0]
        filtered: list[str] = []
        for key in keys:
            seq = self._segment_seq_from_key(key=key)
            if seq is None:
                continue
            if seq >= min_segment_seq:
                filtered.append(key)
        return filtered

    async def _read_segment_events(self, *, key: str) -> list[PersistenceEventV1]:
        raw = await self._store.get_bytes(key=key)
        if raw is None:
            return []
        try:
            payload = gzip.decompress(raw).decode("utf-8")
        except OSError:
            payload = raw.decode("utf-8")
        events: list[PersistenceEventV1] = []
        for line in payload.splitlines():
            if not line.strip():
                continue
            events.append(PersistenceEventV1.model_validate(json.loads(line)))
        return events

    @staticmethod
    def _events_after_watermark(
        *,
        events: list[PersistenceEventV1],
        watermark: tuple[int, int] | None,
    ) -> list[PersistenceEventV1]:
        if watermark is None:
            return events
        return [
            event
            for event in events
            if (event.segment_seq, event.segment_event_index) > watermark
        ]

    @staticmethod
    def _checkpoint_watermark(
        *,
        checkpoint: PersistenceCheckpointV1 | None,
    ) -> tuple[int, int] | None:
        if checkpoint is None:
            return None
        if checkpoint.committed_source_segment_seq >= 0:
            return (
                checkpoint.committed_source_segment_seq,
                checkpoint.committed_source_event_index,
            )
        return (checkpoint.last_segment_seq, checkpoint.last_event_index)

    @staticmethod
    def _segment_seq_from_key(*, key: str) -> int | None:
        filename = key.rsplit("/", 1)[-1]
        if not filename.endswith(".ndjson.gz"):
            return None
        seq = filename.removesuffix(".ndjson.gz")
        if not seq.isdigit():
            return None
        return int(seq)

    @staticmethod
    def _is_valid_pending_timing(*, state: ReplayedMessageState) -> bool:
        if state.attempt_count < 0 or state.attempt_count >= 6:
            return False
        expected_next_due = attempt_deadline_ms(
            state.received_at_ms, state.attempt_count + 1
        )
        return state.next_due_at_ms == expected_next_due
