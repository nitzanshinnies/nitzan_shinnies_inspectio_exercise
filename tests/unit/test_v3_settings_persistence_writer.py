"""P12.3: persistence writer settings parsing/validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from inspectio.v3.settings import V3PersistenceWriterSettings


@pytest.mark.unit
def test_writer_settings_minimal_required_fields() -> None:
    s = V3PersistenceWriterSettings(
        persist_transport_queue_url="https://sqs/persist",
        persistence_s3_bucket="bucket",
    )
    assert s.writer_receive_max_events == 10
    assert s.writer_flush_max_events == 500
    assert s.writer_observability_snapshot_interval_sec == 30
    assert s.writer_observability_queue_age_sample_interval_sec == 30
    assert s.writer_observability_queue_age_timeout_sec == 1.0


@pytest.mark.unit
def test_writer_settings_reject_invalid_receive_max_events() -> None:
    with pytest.raises(ValidationError):
        V3PersistenceWriterSettings(
            persist_transport_queue_url="https://sqs/persist",
            persistence_s3_bucket="bucket",
            writer_receive_max_events=0,
        )


@pytest.mark.unit
def test_writer_settings_resolves_shard_queue_url() -> None:
    s = V3PersistenceWriterSettings(
        persist_transport_shard_count=2,
        persist_transport_queue_urls=["https://sqs/persist-0", "https://sqs/persist-1"],
        writer_shard_id=1,
        persistence_s3_bucket="bucket",
    )
    assert s.resolved_transport_queue_url() == "https://sqs/persist-1"


@pytest.mark.unit
def test_writer_settings_rejects_out_of_range_shard_id() -> None:
    with pytest.raises(ValidationError, match="WRITER_SHARD_ID must be in range"):
        V3PersistenceWriterSettings(
            persist_transport_shard_count=2,
            persist_transport_queue_urls=[
                "https://sqs/persist-0",
                "https://sqs/persist-1",
            ],
            writer_shard_id=2,
            persistence_s3_bucket="bucket",
        )
