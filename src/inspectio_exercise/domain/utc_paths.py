"""UTC terminal key paths — implement to satisfy `tests/reference_spec.py` + plans."""

from __future__ import annotations


def terminal_failed_key(message_id: str, instant_ms: int) -> str:
    raise NotImplementedError


def terminal_success_key(message_id: str, instant_ms: int) -> str:
    raise NotImplementedError


def utc_segments_for_instant_ms(instant_ms: int) -> tuple[str, str, str, str]:
    raise NotImplementedError
