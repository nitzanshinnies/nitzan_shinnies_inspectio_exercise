"""P1 sharding tests (TC-SHA-*)."""

from __future__ import annotations

import pytest

from inspectio.domain.sharding import (
    owned_shard_range,
    shard_for_message,
    validate_total_shards_vs_workers,
)


@pytest.mark.unit
def test_shard_for_message_golden_vector_tc_sha_001() -> None:
    message_id = "123e4567-e89b-12d3-a456-426614174000"
    assert shard_for_message(message_id, 1024) == 457


@pytest.mark.unit
def test_shard_for_message_is_deterministic_tc_sha_002() -> None:
    message_id = "550e8400-e29b-41d4-a716-446655440000"
    first = shard_for_message(message_id, 1024)
    second = shard_for_message(message_id, 1024)
    assert first == second


@pytest.mark.unit
@pytest.mark.parametrize(
    ("total_shards", "worker_count"),
    [(10, 3), (1024, 8), (7, 7), (100, 1)],
)
def test_owned_ranges_partition_shards_exactly_once_tc_sha_003(
    total_shards: int,
    worker_count: int,
) -> None:
    ranges = [
        owned_shard_range(p, total_shards, worker_count) for p in range(worker_count)
    ]
    covered: set[int] = set()
    for start, end_excl in ranges:
        assert start <= end_excl
        for s in range(start, end_excl):
            assert s not in covered
            covered.add(s)
    assert covered == set(range(total_shards))


@pytest.mark.unit
@pytest.mark.parametrize("total_shards", [1, 7, 1024])
def test_shard_for_message_is_within_bounds_tc_sha_003(total_shards: int) -> None:
    shard_id = shard_for_message("00000000-0000-4000-8000-000000000001", total_shards)
    assert 0 <= shard_id < total_shards


@pytest.mark.unit
def test_shard_for_message_rejects_non_positive_total_shards_tc_sha_004() -> None:
    with pytest.raises(ValueError):
        shard_for_message("123e4567-e89b-12d3-a456-426614174000", 0)


@pytest.mark.unit
def test_total_shards_less_than_workers_rejected_tc_sha_004() -> None:
    with pytest.raises(ValueError, match=r"total_shards must be >= worker_count"):
        validate_total_shards_vs_workers(3, 10)
