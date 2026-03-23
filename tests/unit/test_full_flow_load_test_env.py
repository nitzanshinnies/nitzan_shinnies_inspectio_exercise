"""Unit tests for ``scripts/full_flow_load_test`` env helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Script lives under ``scripts/`` (not a package); load by path.
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "full_flow_load_test.py"
_spec = importlib.util.spec_from_file_location("full_flow_load_test", _SCRIPT)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules["full_flow_load_test"] = _mod
_spec.loader.exec_module(_mod)


def test_apply_aws_env_base_urls_uses_defaults_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INSPECTIO_TEST_API_BASE", raising=False)
    monkeypatch.delenv("INSPECTIO_TEST_HEALTH_MONITOR_BASE", raising=False)
    monkeypatch.delenv("INSPECTIO_TEST_PERSISTENCE_BASE", raising=False)
    got = _mod.apply_aws_env_base_urls(
        api_base="http://a",
        health_monitor_base="http://b",
        persistence_base="http://c",
    )
    assert got == ("http://a", "http://b", "http://c")


def test_apply_aws_env_base_urls_overrides_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSPECTIO_TEST_API_BASE", " http://elb ")
    monkeypatch.setenv("INSPECTIO_TEST_HEALTH_MONITOR_BASE", "http://hm")
    monkeypatch.setenv("INSPECTIO_TEST_PERSISTENCE_BASE", "http://persist")
    got = _mod.apply_aws_env_base_urls(
        api_base="http://ignored",
        health_monitor_base="http://ignored",
        persistence_base="http://ignored",
    )
    assert got == ("http://elb", "http://hm", "http://persist")


def test_resolve_drain_poll_keeps_local_default() -> None:
    got = _mod.resolve_drain_poll_sec(
        requested_poll_sec=2.0,
        remote_persistence=False,
        sizes=(10_000, 20_000),
    )
    assert got == 2.0


def test_resolve_drain_poll_uses_remote_default_for_large_remote_batches() -> None:
    got = _mod.resolve_drain_poll_sec(
        requested_poll_sec=2.0,
        remote_persistence=True,
        sizes=(10_000, 20_000),
    )
    assert got == 8.0


def test_resolve_drain_poll_keeps_explicit_remote_override() -> None:
    got = _mod.resolve_drain_poll_sec(
        requested_poll_sec=3.5,
        remote_persistence=True,
        sizes=(20_000,),
    )
    assert got == 3.5
