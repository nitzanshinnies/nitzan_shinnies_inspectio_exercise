"""MemoryLocalS3Provider contract (same semantics as ``plans/LOCAL_S3.md`` §2–§4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from inspectio_exercise.persistence.memory_s3 import MemoryLocalS3Provider


@pytest.fixture
def s3() -> MemoryLocalS3Provider:
    return MemoryLocalS3Provider()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_put_get_round_trip_binary(s3: MemoryLocalS3Provider) -> None:
    body = b"\xff\x00hello"
    await s3.put_object("objects/bin.dat", body)
    assert await s3.get_object("objects/bin.dat") == body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_missing_raises_key_error(s3: MemoryLocalS3Provider) -> None:
    with pytest.raises(KeyError) as exc_info:
        await s3.get_object("no-such-key")
    assert exc_info.value.args[0] == "no-such-key"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_then_get_key_error(s3: MemoryLocalS3Provider) -> None:
    await s3.put_object("gone.json", b"x")
    await s3.delete_object("gone.json")
    with pytest.raises(KeyError):
        await s3.get_object("gone.json")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_missing_idempotent(s3: MemoryLocalS3Provider) -> None:
    await s3.delete_object("never-was.json")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_prefix_sorted_ascending(s3: MemoryLocalS3Provider) -> None:
    await s3.put_object("p/c", b"")
    await s3.put_object("p/a", b"")
    await s3.put_object("p/b", b"")
    out = await s3.list_prefix("p/")
    assert [row["Key"] for row in out] == ["p/a", "p/b", "p/c"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prefix_isolation_shard_style_keys(s3: MemoryLocalS3Provider) -> None:
    await s3.put_object("state/pending/shard-7/msg-a.json", b"1")
    await s3.put_object("state/pending/shard-8/msg-b.json", b"2")
    shard7 = await s3.list_prefix("state/pending/shard-7/")
    assert [row["Key"] for row in shard7] == ["state/pending/shard-7/msg-a.json"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_prefix_isolation_sibling_branches_under_shared_prefix(
    s3: MemoryLocalS3Provider,
) -> None:
    """Same shape as ``test_local_s3_provider.test_u6`` minus disk assertions."""
    await s3.put_object("state/pending/shard-7/msg-a.json", b"1")
    await s3.put_object("state/pending/shard-8/msg-b.json", b"2")
    await s3.put_object("a/b/x", b"3")
    await s3.put_object("a/c/y", b"4")
    shard7 = await s3.list_prefix("state/pending/shard-7/")
    assert [row["Key"] for row in shard7] == ["state/pending/shard-7/msg-a.json"]
    ab = await s3.list_prefix("a/b/")
    assert [row["Key"] for row in ab] == ["a/b/x"]
    ac = await s3.list_prefix("a/c/")
    assert [row["Key"] for row in ac] == ["a/c/y"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad_key",
    ["", "/leading-slash", "a/../b", "../x", ".."],
)
@pytest.mark.asyncio
async def test_rejects_unsafe_object_keys(s3: MemoryLocalS3Provider, bad_key: str) -> None:
    with pytest.raises(ValueError):
        await s3.put_object(bad_key, b"x")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_allows_normal_relative_keys(s3: MemoryLocalS3Provider) -> None:
    """Segments like ``abs`` are fine; rejection targets ``/`` prefix and ``..`` segments."""
    await s3.put_object("abs/leading", b"ok")
    assert await s3.get_object("abs/leading") == b"ok"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_and_delete_validate_keys(s3: MemoryLocalS3Provider) -> None:
    with pytest.raises(ValueError):
        await s3.get_object("a/../b")
    with pytest.raises(ValueError):
        await s3.delete_object("../x")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_content_type_argument_ignored(s3: MemoryLocalS3Provider) -> None:
    await s3.put_object("x.json", b"{}", content_type="application/json")
    await s3.put_object("x.json", b"[]", content_type="text/plain")
    assert await s3.get_object("x.json") == b"[]"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_overwrite_replaces_bytes(s3: MemoryLocalS3Provider) -> None:
    await s3.put_object("k", b"first")
    await s3.put_object("k", b"second")
    assert await s3.get_object("k") == b"second"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_prefix_empty_string_rejected(s3: MemoryLocalS3Provider) -> None:
    with pytest.raises(ValueError, match="prefix"):
        await s3.list_prefix("")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_prefix_max_keys_lexicographic_first_n(s3: MemoryLocalS3Provider) -> None:
    await s3.put_object("p/z", b"")
    await s3.put_object("p/a", b"")
    await s3.put_object("p/m", b"")
    out = await s3.list_prefix("p/", max_keys=2)
    assert [row["Key"] for row in out] == ["p/a", "p/m"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_prefix_rejects_non_positive_max_keys(s3: MemoryLocalS3Provider) -> None:
    with pytest.raises(ValueError, match="max_keys"):
        await s3.list_prefix("p/", max_keys=0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_body_put_get_round_trip(s3: MemoryLocalS3Provider) -> None:
    await s3.put_object("empty.dat", b"")
    assert await s3.get_object("empty.dat") == b""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flush_to_disk_writes_nested_keys(tmp_path: Path) -> None:
    s3 = MemoryLocalS3Provider()
    await s3.put_object("nested/k.json", b'{"a":1}')
    await s3.flush_to_disk(tmp_path)
    path = tmp_path / "nested" / "k.json"
    assert path.is_file()
    assert path.read_bytes() == b'{"a":1}'


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flush_overwrites_existing_file(tmp_path: Path) -> None:
    s3 = MemoryLocalS3Provider()
    await s3.put_object("x.txt", b"v1")
    await s3.flush_to_disk(tmp_path)
    await s3.put_object("x.txt", b"v2")
    await s3.flush_to_disk(tmp_path)
    assert (tmp_path / "x.txt").read_bytes() == b"v2"
