"""P1 model contract tests for Message / RetryStateV1."""

from __future__ import annotations

import pytest

from inspectio.models import Message, RetryStateV1


@pytest.mark.unit
def test_message_fields_match_contract() -> None:
    message = Message(message_id="m1", to="+15550000000", body="hello")
    assert message.message_id == "m1"
    assert message.to == "+15550000000"
    assert message.body == "hello"


@pytest.mark.unit
def test_retry_state_pending_allows_attempt_count_0_to_5() -> None:
    state = RetryStateV1(
        message_id="m1",
        attempt_count=5,
        next_due_at_ms=1_700_000_016_000,
        status="pending",
        last_error="timeout",
        payload={"body": "x", "to": "+1555"},
        updated_at_ms=1_700_000_016_000,
    )
    assert state.attempt_count == 5


@pytest.mark.unit
def test_retry_state_pending_rejects_attempt_count_6_tc_dom_004_invariant() -> None:
    with pytest.raises(ValueError):
        RetryStateV1(
            message_id="m1",
            attempt_count=6,
            next_due_at_ms=1,
            status="pending",
            last_error="boom",
            payload={"body": "x"},
            updated_at_ms=1,
        )


@pytest.mark.unit
def test_retry_state_terminal_failed_requires_attempt_count_6_tc_dom_004_terminal() -> (
    None
):
    state = RetryStateV1(
        message_id="m1",
        attempt_count=6,
        next_due_at_ms=1_700_000_016_000,
        status="failed",
        last_error="timeout",
        payload={"body": "x", "to": "+1555"},
        updated_at_ms=1_700_000_016_000,
    )
    assert state.status == "failed"


@pytest.mark.unit
def test_retry_state_terminal_success_allows_attempt_count_1_tc_dom_005() -> None:
    state = RetryStateV1(
        message_id="m1",
        attempt_count=1,
        next_due_at_ms=1_700_000_000_000,
        status="success",
        last_error=None,
        payload={"body": "x", "to": "+1555"},
        updated_at_ms=1_700_000_000_000,
    )
    assert state.status == "success"


@pytest.mark.unit
def test_retry_state_terminal_success_allows_attempt_count_4_tc_dom_006() -> None:
    state = RetryStateV1(
        message_id="m1",
        attempt_count=4,
        next_due_at_ms=1_700_000_004_000,
        status="success",
        last_error=None,
        payload={"body": "x", "to": "+1555"},
        updated_at_ms=1_700_000_004_000,
    )
    assert state.attempt_count == 4
