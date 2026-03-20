"""Persistence boundary (plans/TESTS.md §4.10) — spy via `RecordingPersistence`."""

from __future__ import annotations

import pytest

from tests.fakes import RecordingPersistence


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recording_persistence_tracks_puts() -> None:
    p = RecordingPersistence()
    await p.put_object("state/pending/shard-0/x.json", b"{}")
    assert p.puts == [("state/pending/shard-0/x.json", b"{}")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_after_put_roundtrip() -> None:
    p = RecordingPersistence()
    await p.put_object("k", b"data")
    assert await p.get_object("k") == b"data"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_prefix_filters_keys() -> None:
    p = RecordingPersistence()
    await p.put_object("state/pending/shard-0/a.json", b"{}")
    await p.put_object("state/pending/shard-1/b.json", b"{}")
    rows = await p.list_prefix("state/pending/shard-0/")
    keys = [r["Key"] for r in rows]
    assert keys == ["state/pending/shard-0/a.json"]
