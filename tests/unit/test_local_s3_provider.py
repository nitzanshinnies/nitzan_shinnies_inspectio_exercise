"""LocalS3Provider contract (plans/LOCAL_S3.md §7).

TDD: defines required behavior before / while implementing
``inspectio_exercise.persistence.local_s3.LocalS3Provider``. Expect **red** until
put/get/delete/list are implemented; keep **green** thereafter.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from inspectio_exercise.persistence.local_s3 import LocalS3Provider


@pytest.fixture
def local_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def s3(local_root: Path) -> LocalS3Provider:
    return LocalS3Provider(local_root)


# --- §7.3 U1–U8 (required) ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u1_put_get_round_trip_binary(s3: LocalS3Provider) -> None:
    body = b"\xff\x00hello"
    await s3.put_object("objects/bin.dat", body)
    assert await s3.get_object("objects/bin.dat") == body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u2_get_missing_raises_key_error(s3: LocalS3Provider) -> None:
    with pytest.raises(KeyError) as exc_info:
        await s3.get_object("no-such-key")
    assert exc_info.value.args[0] == "no-such-key"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u3_delete_then_get_key_error(s3: LocalS3Provider, local_root: Path) -> None:
    await s3.put_object("gone.json", b"x")
    assert (local_root / "gone.json").is_file()
    await s3.delete_object("gone.json")
    assert not (local_root / "gone.json").exists()
    with pytest.raises(KeyError):
        await s3.get_object("gone.json")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u4_delete_missing_idempotent(s3: LocalS3Provider) -> None:
    await s3.delete_object("never-was.json")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u5_list_prefix_sorted_ascending(s3: LocalS3Provider) -> None:
    await s3.put_object("p/c", b"")
    await s3.put_object("p/a", b"")
    await s3.put_object("p/b", b"")
    out = await s3.list_prefix("p/")
    assert [row["Key"] for row in out] == ["p/a", "p/b", "p/c"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u6_prefix_isolation_includes_shard_style_keys(s3: LocalS3Provider) -> None:
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
    ids=["empty", "leading_slash", "dotdot_mid", "dotdot_start", "dotdot_only"],
)
@pytest.mark.asyncio
async def test_u7_rejects_unsafe_object_keys(s3: LocalS3Provider, bad_key: str) -> None:
    with pytest.raises(ValueError):
        await s3.put_object(bad_key, b"x")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u7_allows_normal_relative_keys(s3: LocalS3Provider) -> None:
    """Segments like ``abs`` are fine; rejection targets ``/`` prefix and ``..`` segments."""
    await s3.put_object("abs/leading", b"ok")
    assert await s3.get_object("abs/leading") == b"ok"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u7_get_and_delete_validate_keys(s3: LocalS3Provider) -> None:
    with pytest.raises(ValueError):
        await s3.get_object("a/../b")
    with pytest.raises(ValueError):
        await s3.delete_object("../x")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u8_content_type_argument_ignored_for_bytes_round_trip(s3: LocalS3Provider) -> None:
    await s3.put_object("x.json", b"{}", content_type="application/json")
    await s3.put_object("x.json", b"[]", content_type="text/plain")
    assert await s3.get_object("x.json") == b"[]"


# --- §7.3 additional U9–U13 ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u9_overwrite_replaces_bytes(s3: LocalS3Provider) -> None:
    await s3.put_object("k", b"first")
    await s3.put_object("k", b"second")
    assert await s3.get_object("k") == b"second"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u10_list_prefix_empty_string_rejected(s3: LocalS3Provider) -> None:
    with pytest.raises(ValueError, match="prefix"):
        await s3.list_prefix("")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u11_list_prefix_max_keys_is_lexicographic_first_n(s3: LocalS3Provider) -> None:
    await s3.put_object("p/z", b"")
    await s3.put_object("p/a", b"")
    await s3.put_object("p/m", b"")
    out = await s3.list_prefix("p/", max_keys=2)
    assert [row["Key"] for row in out] == ["p/a", "p/m"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u12_put_creates_nested_dirs_list_skips_empty_dir_without_objects(
    s3: LocalS3Provider, local_root: Path
) -> None:
    (local_root / "orphan").mkdir()
    await s3.put_object("nested/deep/file.txt", b"data")
    assert (local_root / "nested" / "deep" / "file.txt").is_file()
    listed = await s3.list_prefix("nested/")
    assert [row["Key"] for row in listed] == ["nested/deep/file.txt"]
    orphan_list = await s3.list_prefix("orphan/")
    assert orphan_list == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_u13_list_prefix_rejects_non_positive_max_keys(s3: LocalS3Provider) -> None:
    """``max_keys`` validation runs before listing (no objects required)."""
    with pytest.raises(ValueError, match="max_keys"):
        await s3.list_prefix("p/", max_keys=0)


# --- §7.4 checklist ---


@pytest.mark.unit
@pytest.mark.asyncio
async def test_empty_body_put_get_round_trip(s3: LocalS3Provider) -> None:
    await s3.put_object("empty.dat", b"")
    assert await s3.get_object("empty.dat") == b""
