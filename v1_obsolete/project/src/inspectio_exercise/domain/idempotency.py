"""Activation idempotency — matches `tests/reference_spec.ActivationLedgerRef` + CORE_LIFECYCLE §6.2."""

from __future__ import annotations


class ActivationLedger:
    """Mirrors ``ActivationLedgerRef`` in ``tests/reference_spec.py``."""

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
