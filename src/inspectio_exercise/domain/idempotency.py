"""Activation idempotency — implement to satisfy `tests/reference_spec.ActivationLedgerRef` + plans."""

from __future__ import annotations


class ActivationLedger:
    """Must match `ActivationLedgerRef` behavior in `tests/reference_spec.py`."""

    def __init__(self) -> None:
        pass

    def is_terminal(self, message_id: str) -> bool:
        raise NotImplementedError

    def mark_terminal(self, message_id: str) -> None:
        raise NotImplementedError

    def try_activate(self, message_id: str) -> bool:
        raise NotImplementedError
