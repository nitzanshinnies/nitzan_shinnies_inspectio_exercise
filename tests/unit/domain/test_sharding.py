"""P1 sharding tests (TC-SHA-*)."""

from __future__ import annotations

import pytest

from inspectio.domain.sharding import shard_for_message


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
@pytest.mark.parametrize("total_shards", [1, 7, 1024])
def test_shard_for_message_is_within_bounds_tc_sha_003(total_shards: int) -> None:
    shard_id = shard_for_message("00000000-0000-4000-8000-000000000001", total_shards)
    assert 0 <= shard_id < total_shards


@pytest.mark.unit
def test_shard_for_message_rejects_non_positive_total_shards_tc_sha_004() -> None:
    with pytest.raises(ValueError):
        shard_for_message("123e4567-e89b-12d3-a456-426614174000", 0)
