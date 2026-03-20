"""Retry delays and attempt-count rules — implement to satisfy `tests/reference_spec.py` + plans."""

from __future__ import annotations


def attempt_count_is_terminal(attempt_count: int) -> bool:
    raise NotImplementedError


def delay_ms_before_next_attempt_after_failure(attempt_count_when_failed: int) -> int | None:
    raise NotImplementedError


def next_due_at_ms_after_failure(now_ms: int, attempt_count_when_failed: int) -> int | None:
    raise NotImplementedError
