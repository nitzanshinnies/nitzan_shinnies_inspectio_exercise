"""Due selection and tick cadence — implement to satisfy `tests/reference_spec.py` + plans."""

from __future__ import annotations


def elapsed_ms_for_tick_count(tick_count: int, tick_interval_ms: int = 500) -> int:
    raise NotImplementedError


def heap_pop_order(events: list[tuple[int, str]]) -> list[str]:
    raise NotImplementedError


def select_due_message_ids(messages: list[tuple[str, int]], now_ms: int) -> list[str]:
    raise NotImplementedError


def tick_count_for_elapsed_ms(elapsed_ms: int, tick_interval_ms: int = 500) -> int:
    raise NotImplementedError
