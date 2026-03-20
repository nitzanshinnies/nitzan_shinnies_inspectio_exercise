"""How workers interpret mock SMS HTTP status (plans/MOCK_SMS.md §3.3)."""

from __future__ import annotations


def is_failed_send_for_lifecycle(http_status: int) -> bool:
    """Any ``5xx`` is a failed send for retry/terminal rules."""
    return http_status >= 500


def is_successful_send(http_status: int) -> bool:
    """``2xx`` means the simulated carrier accepted the send."""
    return 200 <= http_status < 300
