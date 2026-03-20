"""Sharding and ownership (plans/SHARDING.md, TESTS.md §4.1)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain.sharding import (
    is_shard_owned,
    owned_shard_ids,
    pending_prefix_for_shard,
    pod_index_from_hostname,
    shard_id_for_message,
)


@pytest.mark.unit
def test_shard_id_stable_for_same_message_id() -> None:
    mid = "550e8400-e29b-41d4-a716-446655440000"
    assert shard_id_for_message(mid, 128) == shard_id_for_message(mid, 128)


@pytest.mark.unit
def test_shard_id_in_range() -> None:
    mid = "550e8400-e29b-41d4-a716-446655440000"
    for n in (8, 64, 128):
        sid = shard_id_for_message(mid, n)
        assert 0 <= sid < n


@pytest.mark.unit
def test_owned_shard_range() -> None:
    assert owned_shard_ids(0, 4, 10) == frozenset({0, 1, 2, 3})
    assert owned_shard_ids(1, 4, 10) == frozenset({4, 5, 6, 7})
    assert owned_shard_ids(2, 4, 10) == frozenset({8, 9})


@pytest.mark.unit
def test_owned_shard_empty_when_pod_starts_past_total() -> None:
    assert owned_shard_ids(5, 2, 10) == frozenset()


@pytest.mark.unit
@pytest.mark.parametrize(
    "hostname",
    ["worker-0", "sms-worker-3", "inspectio-worker-12"],
)
def test_pod_index_from_hostname(hostname: str) -> None:
    expected = int(hostname.split("-")[-1])
    assert pod_index_from_hostname(hostname) == expected


@pytest.mark.unit
def test_pod_index_invalid_hostname() -> None:
    with pytest.raises(ValueError):
        pod_index_from_hostname("no-digits-here")


@pytest.mark.unit
def test_is_shard_owned() -> None:
    assert is_shard_owned(0, 0, 4, 16) is True
    assert is_shard_owned(4, 0, 4, 16) is False


@pytest.mark.unit
def test_pending_prefix_format() -> None:
    assert pending_prefix_for_shard(7) == "state/pending/shard-7/"
