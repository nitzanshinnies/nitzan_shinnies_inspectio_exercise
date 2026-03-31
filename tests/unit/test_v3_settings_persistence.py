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


@pytest.mark.unit
def test_persistence_settings_accepts_strict_mode() -> None:
    settings = V3PersistenceSettings(
        persistence_emit_enabled=True,
        persistence_durability_mode="strict",
    )
    assert settings.persistence_emit_enabled is True
    assert settings.persistence_durability_mode == "strict"


@pytest.mark.unit
def test_persistence_settings_rejects_invalid_mode() -> None:
    with pytest.raises(ValidationError):
        V3PersistenceSettings(persistence_durability_mode="invalid")
