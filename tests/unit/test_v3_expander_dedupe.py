"""P3: in-process expander dedupe LRU."""

from __future__ import annotations

import pytest

from inspectio.v3.expander.dedupe import ExpandedBulkDedupe


@pytest.mark.unit
def test_dedupe_lru_evicts_oldest() -> None:
    d = ExpandedBulkDedupe(max_size=3)
    d.mark_expanded("a")
    d.mark_expanded("b")
    d.mark_expanded("c")
    assert d.is_expanded("a")
    d.mark_expanded("d")
    assert not d.is_expanded("a")
    assert d.is_expanded("d")
