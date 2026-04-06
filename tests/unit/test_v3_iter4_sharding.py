"""Unit tests for shard routing (no I/O)."""

from __future__ import annotations

import pytest

from inspectio.v3.iter4_dynamo_wal.sharding import (
    message_shard_id,
    shards_owned_by_worker,
    worker_index_from_hostname,
)


def test_message_shard_id_stable() -> None:
    s = message_shard_id("msg-1", total_shards=16)
    assert s.startswith("shard-")
    assert s == message_shard_id("msg-1", total_shards=16)


def test_message_shard_id_range() -> None:
    for i in range(100):
        sid = message_shard_id(f"id-{i}", total_shards=8)
        idx = int(sid.split("-")[1])
        assert 0 <= idx < 8


def test_worker_index_from_hostname() -> None:
    assert worker_index_from_hostname("sms-worker-0") == 0
    assert worker_index_from_hostname("sms-worker-3") == 3


def test_shards_owned_by_worker() -> None:
    w0 = shards_owned_by_worker(0, total_workers=4, total_shards=8)
    assert w0 == ["shard-00", "shard-04"]
    w1 = shards_owned_by_worker(1, total_workers=4, total_shards=8)
    assert w1 == ["shard-01", "shard-05"]


def test_shards_invalid_worker() -> None:
    with pytest.raises(ValueError):
        shards_owned_by_worker(4, total_workers=4, total_shards=8)
