"""Contract checks for the in-memory PersistencePort fake (plans/LOCAL_S3.md §4.1)."""

from __future__ import annotations

import pytest

from obsolete_tests.fakes import RecordingPersistence


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_prefix_max_keys_is_lexicographic_first_n() -> None:
    p = RecordingPersistence()
    # Insertion order differs from lexicographic order; cap must apply after sort.
    await p.put_object("p/z", b"")
    await p.put_object("p/a", b"")
    await p.put_object("p/m", b"")
    out = await p.list_prefix("p/", max_keys=2)
    assert [row["Key"] for row in out] == ["p/a", "p/m"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_prefix_rejects_non_positive_max_keys() -> None:
    p = RecordingPersistence()
    await p.put_object("p/a", b"")
    with pytest.raises(ValueError, match="max_keys"):
        await p.list_prefix("p/", max_keys=0)
