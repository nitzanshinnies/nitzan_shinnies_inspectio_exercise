"""Idempotency (plans/CORE_LIFECYCLE.md §6.2, REST_API.md §5.2)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain.idempotency import ActivationLedger


@pytest.mark.unit
def test_duplicate_activation_rejected() -> None:
    ledger = ActivationLedger()
    assert ledger.try_activate("m1") is True
    assert ledger.try_activate("m1") is False


@pytest.mark.unit
def test_replay_after_terminal_rejected() -> None:
    ledger = ActivationLedger()
    assert ledger.try_activate("m1") is True
    ledger.mark_terminal("m1")
    assert ledger.try_activate("m1") is False


@pytest.mark.unit
def test_distinct_messages_independent() -> None:
    ledger = ActivationLedger()
    assert ledger.try_activate("a") is True
    assert ledger.try_activate("b") is True
