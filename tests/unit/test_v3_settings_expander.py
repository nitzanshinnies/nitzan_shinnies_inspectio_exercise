"""P3: V3ExpanderSettings validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from inspectio.v3.settings import V3ExpanderSettings


@pytest.mark.unit
def test_expander_settings_rejects_url_count_mismatch() -> None:
    with pytest.raises(ValidationError):
        V3ExpanderSettings(
            bulk_queue_url="https://b",
            send_shard_count=2,
            send_queue_urls=["http://a"],
        )


@pytest.mark.unit
def test_expander_settings_accepts_matching_urls() -> None:
    s = V3ExpanderSettings(
        bulk_queue_url="https://bulk",
        send_shard_count=2,
        send_queue_urls=["http://s0", "http://s1"],
    )
    assert s.send_queue_urls == ["http://s0", "http://s1"]
