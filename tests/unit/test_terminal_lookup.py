"""Terminal prefix helpers for worker idempotency."""

from __future__ import annotations

import pytest

from inspectio_exercise.worker.terminal_lookup import (
    key_matches_message_terminal,
    terminal_prefixes_for_lookback,
)

pytestmark = pytest.mark.unit


def test_terminal_prefixes_for_lookback_length() -> None:
    prefixes = terminal_prefixes_for_lookback(
        lookback_hours=2,
        now_ms=1_700_000_000_000,
        tree_root="state/success",
    )
    assert len(prefixes) == 3
    assert all(p.startswith("state/success/") for p in prefixes)


def test_key_matches_message_terminal() -> None:
    assert key_matches_message_terminal("state/success/2024/01/02/03/mid.json", "mid")
    assert not key_matches_message_terminal("state/success/2024/01/02/03/other.json", "mid")
