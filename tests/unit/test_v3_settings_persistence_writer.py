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


@pytest.mark.unit
def test_writer_settings_reject_invalid_receive_max_events() -> None:
    with pytest.raises(ValidationError):
        V3PersistenceWriterSettings(
            persist_transport_queue_url="https://sqs/persist",
            persistence_s3_bucket="bucket",
            writer_receive_max_events=0,
        )
