"""Deterministic shard assignment — implement to satisfy `tests/reference_spec.py` + plans."""

from __future__ import annotations


def is_shard_owned(
    shard_id: int,
    pod_index: int,
    shards_per_pod: int,
    total_shards: int,
) -> bool:
    raise NotImplementedError


def owned_shard_ids(pod_index: int, shards_per_pod: int, total_shards: int) -> frozenset[int]:
    raise NotImplementedError


def pending_prefix_for_shard(shard_id: int) -> str:
    raise NotImplementedError


def pod_index_from_hostname(hostname: str) -> int:
    raise NotImplementedError


def shard_id_for_message(message_id: str, total_shards: int) -> int:
    raise NotImplementedError
