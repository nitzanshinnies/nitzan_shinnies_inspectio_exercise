"""Tests for repeat count bounds shared with L2."""

from __future__ import annotations

import pytest

from inspectio.v3.load_harness.repeat_limits import (
    L2_REPEAT_COUNT_MAX,
    validated_repeat_count,
)


def test_validated_repeat_count_accepts_bounds() -> None:
    assert validated_repeat_count(1) == 1
    assert validated_repeat_count(L2_REPEAT_COUNT_MAX) == L2_REPEAT_COUNT_MAX


def test_validated_repeat_count_rejects_below_one() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        validated_repeat_count(0)


def test_validated_repeat_count_rejects_above_l2_max() -> None:
    with pytest.raises(ValueError, match="L2"):
        validated_repeat_count(L2_REPEAT_COUNT_MAX + 1)
