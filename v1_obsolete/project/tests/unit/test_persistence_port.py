"""``PersistencePort`` contract — ``LocalS3Provider`` (plans/TESTS.md §4.10, LOCAL_S3.md)."""

from __future__ import annotations

import pytest

from inspectio_exercise.persistence.local_s3 import LocalS3Provider


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_s3_provider_satisfies_persistence_port_put_get(tmp_path) -> None:
    s3 = LocalS3Provider(tmp_path)
    key = "state/pending/shard-0/msg.json"
    body = b'{"messageId":"msg","status":"pending"}'
    await s3.put_object(key, body, content_type="application/json")
    assert await s3.get_object(key) == body


@pytest.mark.unit
@pytest.mark.asyncio
async def test_local_s3_provider_delete_and_list_prefix(tmp_path) -> None:
    s3 = LocalS3Provider(tmp_path)
    await s3.put_object("state/pending/shard-1/a.json", b"a")
    await s3.put_object("state/pending/shard-1/b.json", b"b")
    keys = await s3.list_prefix("state/pending/shard-1/", max_keys=10)
    assert {r["Key"] for r in keys} == {
        "state/pending/shard-1/a.json",
        "state/pending/shard-1/b.json",
    }
    await s3.delete_object("state/pending/shard-1/a.json")
    with pytest.raises(KeyError):
        await s3.get_object("state/pending/shard-1/a.json")
