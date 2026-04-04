"""P12.1: persistence feature-flag settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from inspectio.v3.settings import V3PersistenceSettings


@pytest.mark.unit
def test_persistence_settings_defaults_safe_baseline() -> None:
    settings = V3PersistenceSettings()
    assert settings.persistence_emit_enabled is False
    assert settings.persistence_durability_mode == "best_effort"
    assert settings.persist_transport_queue_url is None
    assert settings.persist_transport_max_attempts == 4
    assert settings.persist_transport_batch_max_events == 10
    assert settings.expose_persistence_transport_metrics is False


@pytest.mark.unit
def test_persistence_settings_accepts_strict_mode() -> None:
    settings = V3PersistenceSettings(
        persistence_emit_enabled=True,
        persistence_durability_mode="strict",
        persist_transport_queue_url="https://sqs/persist",
        persist_transport_dlq_url="https://sqs/persist-dlq",
    )
    assert settings.persistence_emit_enabled is True
    assert settings.persistence_durability_mode == "strict"
    assert settings.persist_transport_queue_url == "https://sqs/persist"


@pytest.mark.unit
def test_persistence_settings_rejects_invalid_mode() -> None:
    with pytest.raises(ValidationError):
        V3PersistenceSettings(persistence_durability_mode="invalid")


@pytest.mark.unit
def test_persistence_settings_accepts_sharded_queue_urls() -> None:
    settings = V3PersistenceSettings(
        persistence_emit_enabled=True,
        persist_transport_shard_count=2,
        persist_transport_queue_urls=["https://sqs/persist-0", "https://sqs/persist-1"],
        persist_transport_dlq_urls=["https://sqs/dlq-0", "https://sqs/dlq-1"],
    )
    assert settings.persist_transport_shard_count == 2
    assert settings.persist_transport_queue_urls[1] == "https://sqs/persist-1"


@pytest.mark.unit
def test_persistence_settings_rejects_shard_count_mismatch() -> None:
    with pytest.raises(ValidationError, match="QUEUE_URLS length must equal"):
        V3PersistenceSettings(
            persistence_emit_enabled=True,
            persist_transport_shard_count=2,
            persist_transport_queue_urls=["https://sqs/persist-0"],
        )
