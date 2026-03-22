"""Send ``inspectio_exercise`` logs to stderr so Docker/Kubernetes log collectors see them."""

from __future__ import annotations

import logging
import os
import sys

_PACKAGES_LOGGER_NAME: str = "inspectio_exercise"
_STDERR_DATE_FORMAT: str = "%Y-%m-%dT%H:%M:%S"
_STDERR_LOG_FORMAT: str = "%(asctime)s %(levelname)s %(name)s %(message)s"

_ENV_SKIP_CONTAINER_LOGGING: str = "INSPECTIO_SKIP_CONTAINER_LOGGING"


def ensure_inspectio_stderr_logging() -> None:
    """Attach a stderr :class:`logging.StreamHandler` to the package logger (idempotent).

    Container runtimes attach to the process' stdout and stderr; this makes application
    logs (including ``inspectio_perf`` lines) show up in ``docker logs`` and
    ``kubectl logs`` when services are started via :mod:`inspectio_exercise.cli`.

    Set ``INSPECTIO_SKIP_CONTAINER_LOGGING=1`` to skip (e.g. tests or custom logging).
    """
    skip = os.environ.get(_ENV_SKIP_CONTAINER_LOGGING, "").strip().lower()
    if skip in ("1", "true", "yes"):
        return
    pkg = logging.getLogger(_PACKAGES_LOGGER_NAME)
    if pkg.handlers:
        return
    pkg.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(_STDERR_LOG_FORMAT, datefmt=_STDERR_DATE_FORMAT))
    pkg.addHandler(handler)
    pkg.propagate = False
