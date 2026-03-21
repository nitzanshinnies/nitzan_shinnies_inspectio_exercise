"""Sharding — production must match `tests/reference_spec.py` (TESTS.md §4.1, SHARDING.md)."""

from __future__ import annotations

import pytest

from inspectio_exercise.domain import sharding as sharding_mod
from tests import reference_spec as spec


@pytest.mark.unit
def test_shard_id_matches_spec_stable() -> None:
    mid = "550e8400-e29b-41d4-a716-446655440000"
    assert sharding_mod.shard_id_for_message(mid, 128) == spec.shard_id_for_message(mid, 128)
    assert sharding_mod.shard_id_for_message(mid, 128) == sharding_mod.shard_id_for_message(
        mid, 128
    )


@pytest.mark.unit
def test_shard_id_in_range_matches_spec() -> None:
    mid = "550e8400-e29b-41d4-a716-446655440000"
    for n in (8, 64, 128):
        sid = sharding_mod.shard_id_for_message(mid, n)
        assert sid == spec.shard_id_for_message(mid, n)
        assert 0 <= sid < n


@pytest.mark.unit
def test_owned_shard_range_matches_spec() -> None:
    for args in ((0, 4, 10), (1, 4, 10), (2, 4, 10), (5, 2, 10)):
        assert sharding_mod.owned_shard_ids(*args) == spec.owned_shard_ids(*args)


@pytest.mark.unit
@pytest.mark.parametrize(
    "hostname",
    ["worker-0", "sms-worker-3", "inspectio-worker-12"],
)
def test_pod_index_matches_spec(hostname: str) -> None:
    assert sharding_mod.pod_index_from_hostname(hostname) == spec.pod_index_from_hostname(hostname)


@pytest.mark.unit
def test_pod_index_invalid_hostname() -> None:
    with pytest.raises(ValueError):
        sharding_mod.pod_index_from_hostname("no-digits-here")


@pytest.mark.unit
def test_is_shard_owned_matches_spec() -> None:
    assert sharding_mod.is_shard_owned(0, 0, 4, 16) == spec.is_shard_owned(0, 0, 4, 16)
    assert sharding_mod.is_shard_owned(4, 0, 4, 16) == spec.is_shard_owned(4, 0, 4, 16)


@pytest.mark.unit
def test_pending_prefix_matches_spec() -> None:
    assert sharding_mod.pending_prefix_for_shard(7) == spec.pending_prefix_for_shard(7)
