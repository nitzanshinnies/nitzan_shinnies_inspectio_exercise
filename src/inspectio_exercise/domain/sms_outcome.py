"""Mock SMS HTTP status classification — matches ``tests/reference_spec.py`` + MOCK_SMS.md."""

from __future__ import annotations


def is_failed_send_for_lifecycle(http_status: int) -> bool:
    return http_status >= 500


def is_successful_send(http_status: int) -> bool:
    return 200 <= http_status < 300
