"""Worker interpretation of mock SMS HTTP status — implement to satisfy `tests/reference_spec.py` + MOCK_SMS.md."""

from __future__ import annotations


def is_failed_send_for_lifecycle(http_status: int) -> bool:
    raise NotImplementedError


def is_successful_send(http_status: int) -> bool:
    raise NotImplementedError
