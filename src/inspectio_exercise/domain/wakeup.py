"""Due-message selection and tick cadence (plans/CORE_LIFECYCLE.md §4.3)."""

from __future__ import annotations

import heapq


def elapsed_ms_for_tick_count(tick_count: int, tick_interval_ms: int = 500) -> int:
    """Wall-clock elapsed time matching `tick_count` full ticks at `tick_interval_ms`."""
    if tick_count < 0 or tick_interval_ms <= 0:
        raise ValueError("tick_count must be non-negative and tick_interval_ms positive")
    return tick_count * tick_interval_ms


def heap_pop_order(events: list[tuple[int, str]]) -> list[str]:
    """
    Min-heap pop order for `(next_due_at_ms, message_id)`.

    Yields earliest `next_due_at` first; ties break by `message_id` (heapq with tuples).
    """
    heap = list(events)
    heapq.heapify(heap)
    return [heapq.heappop(heap)[1] for _ in range(len(heap))]


def select_due_message_ids(messages: list[tuple[str, int]], now_ms: int) -> list[str]:
    """Messages with `nextDueAt <= now`, ordered by `nextDueAt` then `message_id`."""
    due = [(mid, t) for mid, t in messages if t <= now_ms]
    due.sort(key=lambda x: (x[1], x[0]))
    return [mid for mid, _ in due]


def tick_count_for_elapsed_ms(elapsed_ms: int, tick_interval_ms: int = 500) -> int:
    """How many full `tick_interval_ms` ticks fit in `elapsed_ms` (floor)."""
    if elapsed_ms < 0 or tick_interval_ms <= 0:
        raise ValueError("elapsed_ms must be non-negative and tick_interval_ms positive")
    return elapsed_ms // tick_interval_ms
