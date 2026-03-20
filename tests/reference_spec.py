"""
Canonical behavior for domain logic — **spec for TDD**.

Production code under `inspectio_exercise.domain` must match these functions.
Algorithms are fixed here so tests stay red until implementation is correct.

- **Sharding:** `SHARDING.md` §2.1 — `int.from_bytes(sha256(message_id UTF-8) digest, big) % TOTAL_SHARDS`
  (full 32-byte digest as unsigned integer, not a truncated digest).
- **Retry:** `PLAN.md` §5 / `CORE_LIFECYCLE.md` §4.1 — delays before attempts #2–#6:
  500ms, 2s, 4s, 8s, 16s after failures at `attemptCount` 0..4; no further delay after
  the 6th failed send (`attemptCount` was 5 → terminal).
- **Terminal attemptCount:** `PLAN.md` §5 — terminal when `attemptCount == 6` (not `>=`).
"""

from __future__ import annotations

import hashlib
import heapq
import re
from datetime import datetime, timezone


def attempt_count_is_terminal(attempt_count: int) -> bool:
    """Pending record is terminal failed only when `attemptCount == 6` (PLAN.md §5)."""
    return attempt_count == 6


def delay_ms_before_next_attempt_after_failure(attempt_count_when_failed: int) -> int | None:
    """After a failed send, `attemptCount` was `attempt_count_when_failed` (0..5)."""
    if attempt_count_when_failed < 0 or attempt_count_when_failed > 5:
        raise ValueError("attempt_count_when_failed must be in 0..5")
    if attempt_count_when_failed == 5:
        return None
    delays = (500, 2_000, 4_000, 8_000, 16_000)
    return delays[attempt_count_when_failed]


def elapsed_ms_for_tick_count(tick_count: int, tick_interval_ms: int = 500) -> int:
    if tick_count < 0 or tick_interval_ms <= 0:
        raise ValueError("tick_count must be non-negative and tick_interval_ms positive")
    return tick_count * tick_interval_ms


def heap_pop_order(events: list[tuple[int, str]]) -> list[str]:
    heap = list(events)
    heapq.heapify(heap)
    return [heapq.heappop(heap)[1] for _ in range(len(heap))]


def is_shard_owned(
    shard_id: int,
    pod_index: int,
    shards_per_pod: int,
    total_shards: int,
) -> bool:
    return shard_id in owned_shard_ids(pod_index, shards_per_pod, total_shards)


def is_failed_send_for_lifecycle(http_status: int) -> bool:
    return http_status >= 500


def is_successful_send(http_status: int) -> bool:
    return 200 <= http_status < 300


def next_due_at_ms_after_failure(now_ms: int, attempt_count_when_failed: int) -> int | None:
    delay = delay_ms_before_next_attempt_after_failure(attempt_count_when_failed)
    if delay is None:
        return None
    return now_ms + delay


def owned_shard_ids(pod_index: int, shards_per_pod: int, total_shards: int) -> frozenset[int]:
    if total_shards < 0 or shards_per_pod < 0:
        raise ValueError("total_shards and shards_per_pod must be non-negative")
    if total_shards == 0:
        return frozenset()
    start = pod_index * shards_per_pod
    if start >= total_shards:
        return frozenset()
    end = min((pod_index + 1) * shards_per_pod, total_shards)
    return frozenset(range(start, end))


def pending_prefix_for_shard(shard_id: int) -> str:
    return f"state/pending/shard-{shard_id}/"


def pod_index_from_hostname(hostname: str) -> int:
    m = re.search(r"(?:^|-)(\d+)$", hostname.strip())
    if not m:
        raise ValueError(f"cannot derive pod index from hostname: {hostname!r}")
    return int(m.group(1))


def select_due_message_ids(messages: list[tuple[str, int]], now_ms: int) -> list[str]:
    due = [(mid, t) for mid, t in messages if t <= now_ms]
    due.sort(key=lambda x: (x[1], x[0]))
    return [mid for mid, _ in due]


def shard_id_for_message(message_id: str, total_shards: int) -> int:
    if total_shards <= 0:
        raise ValueError("total_shards must be positive")
    digest = hashlib.sha256(message_id.encode("utf-8")).digest()
    value = int.from_bytes(digest, "big")
    return value % total_shards


def terminal_failed_key(message_id: str, instant_ms: int) -> str:
    yyyy, mm, dd, hh = utc_segments_for_instant_ms(instant_ms)
    return f"state/failed/{yyyy}/{mm}/{dd}/{hh}/{message_id}.json"


def terminal_success_key(message_id: str, instant_ms: int) -> str:
    yyyy, mm, dd, hh = utc_segments_for_instant_ms(instant_ms)
    return f"state/success/{yyyy}/{mm}/{dd}/{hh}/{message_id}.json"


def tick_count_for_elapsed_ms(elapsed_ms: int, tick_interval_ms: int = 500) -> int:
    if elapsed_ms < 0 or tick_interval_ms <= 0:
        raise ValueError("elapsed_ms must be non-negative and tick_interval_ms positive")
    return elapsed_ms // tick_interval_ms


def utc_segments_for_instant_ms(instant_ms: int) -> tuple[str, str, str, str]:
    dt = datetime.fromtimestamp(instant_ms / 1000.0, tz=timezone.utc)
    return (
        f"{dt.year:04d}",
        f"{dt.month:02d}",
        f"{dt.day:02d}",
        f"{dt.hour:02d}",
    )


class ActivationLedgerRef:
    """Reference idempotency semantics (CORE_LIFECYCLE §6.2)."""

    def __init__(self) -> None:
        self._pending: set[str] = set()
        self._terminal: set[str] = set()

    def is_terminal(self, message_id: str) -> bool:
        return message_id in self._terminal

    def mark_terminal(self, message_id: str) -> None:
        self._pending.discard(message_id)
        self._terminal.add(message_id)

    def try_activate(self, message_id: str) -> bool:
        if message_id in self._terminal or message_id in self._pending:
            return False
        self._pending.add(message_id)
        return True
