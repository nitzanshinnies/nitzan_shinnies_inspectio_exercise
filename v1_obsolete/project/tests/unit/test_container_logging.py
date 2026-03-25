"""Container-friendly logging bootstrap for Docker/Kubernetes."""

from __future__ import annotations

import logging
import sys

import pytest

from inspectio_exercise.common.container_logging import ensure_inspectio_stderr_logging

pytestmark = pytest.mark.unit


@pytest.fixture
def clean_inspectio_logger() -> None:
    pkg = logging.getLogger("inspectio_exercise")
    before = list(pkg.handlers)
    old_level = pkg.level
    old_propagate = pkg.propagate
    for h in before:
        pkg.removeHandler(h)
    pkg.setLevel(logging.NOTSET)
    pkg.propagate = True
    yield
    for h in list(pkg.handlers):
        pkg.removeHandler(h)
    for h in before:
        pkg.addHandler(h)
    pkg.setLevel(old_level)
    pkg.propagate = old_propagate


def test_ensure_inspectio_stderr_logging_adds_stderr_handler(
    clean_inspectio_logger: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("INSPECTIO_SKIP_CONTAINER_LOGGING", raising=False)
    pkg = logging.getLogger("inspectio_exercise")
    ensure_inspectio_stderr_logging()
    assert len(pkg.handlers) == 1
    assert isinstance(pkg.handlers[0], logging.StreamHandler)
    assert pkg.handlers[0].stream is sys.stderr
    assert pkg.propagate is False


def test_ensure_inspectio_stderr_logging_respects_skip_env(
    clean_inspectio_logger: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSPECTIO_SKIP_CONTAINER_LOGGING", "1")
    pkg = logging.getLogger("inspectio_exercise")
    ensure_inspectio_stderr_logging()
    assert pkg.handlers == []
