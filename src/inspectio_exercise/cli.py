from __future__ import annotations

import os

import uvicorn


def run_api() -> None:
    uvicorn.run(
        "inspectio_exercise.api.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("INSPECTIO_API_PORT", "8000")),
    )


def run_health_monitor() -> None:
    uvicorn.run(
        "inspectio_exercise.health_monitor.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("INSPECTIO_HEALTH_MONITOR_PORT", "8003")),
    )


def run_mock_sms() -> None:
    uvicorn.run(
        "inspectio_exercise.mock_sms.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("INSPECTIO_MOCK_SMS_PORT", "8080")),
    )


def run_notification() -> None:
    uvicorn.run(
        "inspectio_exercise.notification.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("INSPECTIO_NOTIFICATION_PORT", "8002")),
    )


def run_persistence() -> None:
    uvicorn.run(
        "inspectio_exercise.persistence.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("INSPECTIO_PERSISTENCE_PORT", "8001")),
    )


def run_worker() -> None:
    uvicorn.run(
        "inspectio_exercise.worker.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("INSPECTIO_WORKER_PORT", "8004")),
    )
