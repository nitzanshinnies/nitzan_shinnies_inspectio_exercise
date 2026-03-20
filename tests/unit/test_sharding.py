"""Shard id and worker ownership (TESTS.md §4.1, SHARDING.md)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.skip(reason="Skeleton: deterministic shard_id (TESTS.md §4.1)")
def test_shard_id_stable_for_message_id() -> None:
    """Same messageId + TOTAL_SHARDS → same shard_id."""


@pytest.mark.skip(reason="Skeleton: pod_index shard range (TESTS.md §4.1)")
def test_owned_shard_range_for_pod_index() -> None:
    """range(pod_index * spp, (pod_index+1) * spp)."""


@pytest.mark.skip(reason="Skeleton: HOSTNAME → pod_index (TESTS.md §4.1)")
def test_hostname_parses_to_pod_index() -> None:
    """worker-0 style names."""


@pytest.mark.skip(reason="Skeleton: ignore foreign shard messages (TESTS.md §4.1)")
def test_worker_ignores_unowned_shard() -> None:
    """No writes to non-owned pending prefixes."""
