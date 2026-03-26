"""Idempotency — `ActivationLedger` must mirror `tests/reference_spec.ActivationLedgerRef` (TESTS.md §4.8, CORE_LIFECYCLE §6.2)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain.idempotency import ActivationLedger
from obsolete_tests.reference_spec import ActivationLedgerRef


@pytest.mark.unit
def test_duplicate_activation_rejected_matches_ref() -> None:
    ref = ActivationLedgerRef()
    impl = ActivationLedger()
    assert impl.try_activate("m1") == ref.try_activate("m1")
    assert impl.try_activate("m1") == ref.try_activate("m1")


@pytest.mark.unit
def test_replay_after_terminal_rejected_matches_ref() -> None:
    ref = ActivationLedgerRef()
    impl = ActivationLedger()
    assert impl.try_activate("m1") == ref.try_activate("m1")
    impl.mark_terminal("m1")
    ref.mark_terminal("m1")
    assert impl.try_activate("m1") == ref.try_activate("m1")


@pytest.mark.unit
def test_distinct_messages_independent_matches_ref() -> None:
    ref = ActivationLedgerRef()
    impl = ActivationLedger()
    assert impl.try_activate("a") == ref.try_activate("a")
    assert impl.try_activate("b") == ref.try_activate("b")
