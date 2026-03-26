"""P0 exit criteria: importable package (plans/IMPLEMENTATION_PHASES.md P0)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import inspectio


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_import_inspectio_package() -> None:
    assert inspectio.__package__ == "inspectio"


@pytest.mark.unit
def test_inspectio_version_matches_pyproject() -> None:
    raw = (_repo_root() / "pyproject.toml").read_bytes()
    data = tomllib.loads(raw.decode())
    expected = data["project"]["version"]
    assert inspectio.__version__ == expected


@pytest.mark.unit
def test_inspectio_version_is_non_empty_string() -> None:
    assert isinstance(inspectio.__version__, str)
    assert len(inspectio.__version__) > 0
