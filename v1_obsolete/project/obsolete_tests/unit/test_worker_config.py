"""Worker environment validation (plans/TEST_LIST.md TC-SH-08)."""

from __future__ import annotations

import pytest

from inspectio_exercise.worker.config import load_worker_settings

pytestmark = pytest.mark.unit


def test_load_worker_settings_rejects_non_positive_total_shards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOTAL_SHARDS", "0")
    monkeypatch.setenv("SHARDS_PER_POD", "1")
    with pytest.raises(ValueError, match="TOTAL_SHARDS"):
        load_worker_settings()


def test_load_worker_settings_rejects_negative_total_shards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOTAL_SHARDS", "-1")
    monkeypatch.setenv("SHARDS_PER_POD", "1")
    with pytest.raises(ValueError, match="TOTAL_SHARDS"):
        load_worker_settings()


def test_load_worker_settings_rejects_non_positive_shards_per_pod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOTAL_SHARDS", "4")
    monkeypatch.setenv("SHARDS_PER_POD", "0")
    with pytest.raises(ValueError, match="SHARDS_PER_POD"):
        load_worker_settings()
