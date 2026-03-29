"""P0: pytest declares required markers and collects only tests/ (see pyproject.toml)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REQUIRED_MARKERS = frozenset({"unit", "integration", "e2e", "performance"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_pyproject_declares_required_pytest_markers() -> None:
    raw = (_repo_root() / "pyproject.toml").read_bytes()
    data = tomllib.loads(raw.decode())
    ini = data["tool"]["pytest"]["ini_options"]
    assert ini.get("testpaths") == ["tests"]
    marker_lines: list[str] = ini["markers"]
    declared = {line.split(":", 1)[0].strip() for line in marker_lines}
    missing = REQUIRED_MARKERS - declared
    assert not missing, f"Missing markers in pyproject.toml: {sorted(missing)}"
