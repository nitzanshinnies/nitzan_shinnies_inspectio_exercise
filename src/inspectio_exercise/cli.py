from __future__ import annotations

import os

import uvicorn

from inspectio_exercise.common.container_logging import ensure_inspectio_stderr_logging


def _serve(app: str, *, port_env: str, default_port: str) -> None:
    ensure_inspectio_stderr_logging()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get(port_env, default_port)),
    )


def run_api() -> None:
    _serve("inspectio_exercise.api.app:app", port_env="INSPECTIO_API_PORT", default_port="8000")


def run_health_monitor() -> None:
    _serve(
        "inspectio_exercise.health_monitor.app:app",
        port_env="INSPECTIO_HEALTH_MONITOR_PORT",
        default_port="8003",
    )


def run_mock_sms() -> None:
    _serve(
        "inspectio_exercise.mock_sms.app:app",
        port_env="INSPECTIO_MOCK_SMS_PORT",
        default_port="8080",
    )


def run_notification() -> None:
    _serve(
        "inspectio_exercise.notification.app:app",
        port_env="INSPECTIO_NOTIFICATION_PORT",
        default_port="8002",
    )


def run_persistence() -> None:
    _serve(
        "inspectio_exercise.persistence.app:app",
        port_env="INSPECTIO_PERSISTENCE_PORT",
        default_port="8001",
    )


def run_worker() -> None:
    _serve(
        "inspectio_exercise.worker.app:app",
        port_env="INSPECTIO_WORKER_PORT",
        default_port="8004",
    )
