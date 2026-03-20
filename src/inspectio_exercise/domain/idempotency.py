"""Activation idempotency tracking (plans/CORE_LIFECYCLE.md §6.2, REST_API.md §5.2)."""

from __future__ import annotations


class ActivationLedger:
    """
    Tracks which `message_id` values have been accepted for pending activation.

    Duplicate activations for the same id are rejected; terminal ids cannot be
    re-activated.
    """

    def __init__(self) -> None:
        self._pending: set[str] = set()
        self._terminal: set[str] = set()

    def is_terminal(self, message_id: str) -> bool:
        return message_id in self._terminal

    def mark_terminal(self, message_id: str) -> None:
        self._pending.discard(message_id)
        self._terminal.add(message_id)

    def try_activate(self, message_id: str) -> bool:
        """
        If `message_id` may start a new pending activation, register it and return True.

        Returns False if already pending or already terminal.
        """
        if message_id in self._terminal or message_id in self._pending:
            return False
        self._pending.add(message_id)
        return True
