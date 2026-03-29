"""P3: fan-out, sharding, chunking (plans/v3_phases/P3_EXPANDER.md)."""

from __future__ import annotations

import pytest

from inspectio.v3.domain.shard_index import stable_shard_index
from inspectio.v3.expander.fanout import bulk_to_send_units, chunk_fixed_size
from inspectio.v3.expander.sharding import shard_for_message_id
from inspectio.v3.schemas.bulk_intent import BulkIntentV1


@pytest.mark.unit
def test_shard_for_message_id_stable_and_in_range() -> None:
    mid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    a = shard_for_message_id(mid, 4)
    b = shard_for_message_id(mid, 4)
    assert a == b
    assert 0 <= a < 4


@pytest.mark.unit
def test_stable_shard_matches_expander_shard_for_uuid_like_ids() -> None:
    mid = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    k = 3
    assert shard_for_message_id(mid, k) == stable_shard_index(key=mid, shard_count=k)


@pytest.mark.unit
def test_bulk_to_send_units_count_and_fields() -> None:
    bulk = BulkIntentV1(
        trace_id="t",
        batch_correlation_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        idempotency_key="i",
        count=4,
        body="payload",
        received_at_ms=123,
    )
    ids = iter(["m0", "m1", "m2", "m3"])
    units = bulk_to_send_units(bulk, shard_count=2, new_message_id=lambda: next(ids))
    assert len(units) == 4
    for u in units:
        assert u.body == "payload"
        assert u.received_at_ms == 123
        assert u.batch_correlation_id == bulk.batch_correlation_id
        assert u.trace_id == "t"
        assert u.attempts_completed == 0
        assert 0 <= u.shard < 2


@pytest.mark.unit
def test_chunk_fixed_size_ten() -> None:
    bulk = BulkIntentV1(
        trace_id="t",
        batch_correlation_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        idempotency_key="i",
        count=1,
        body="x",
        received_at_ms=0,
    )
    units = bulk_to_send_units(bulk, shard_count=1, new_message_id=lambda: "only")
    units = units * 11
    chunks = list(chunk_fixed_size(units, 10))
    assert len(chunks) == 2
    assert len(chunks[0]) == 10
    assert len(chunks[1]) == 1


@pytest.mark.unit
def test_chunk_fixed_size_rejects_zero() -> None:
    bulk = BulkIntentV1(
        trace_id="t",
        batch_correlation_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        idempotency_key="i",
        count=1,
        body="x",
        received_at_ms=0,
    )
    u = bulk_to_send_units(bulk, shard_count=1)[0]
    with pytest.raises(ValueError):
        list(chunk_fixed_size([u], 0))


@pytest.mark.unit
def test_bulk_to_send_units_shard_follows_message_id() -> None:
    bulk = BulkIntentV1(
        trace_id="t",
        batch_correlation_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        idempotency_key="i",
        count=1,
        body="x",
        received_at_ms=0,
    )
    units = bulk_to_send_units(
        bulk,
        shard_count=5,
        new_message_id=lambda: "fixed-mid-uuid-00000000-0000-4000-8000-000000000001",
    )
    assert units[0].shard == shard_for_message_id(units[0].message_id, 5)
