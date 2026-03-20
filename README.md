# Inspectio exercise

Distributed **SMS retry scheduler** per `plans/` (S3 truth, workers, notification + Redis, mock SMS, health monitor).

## Layout (skeleton)

| Python package / app | Role | Default port |
|---------------------|------|--------------|
| `inspectio_exercise.api` | Public REST API | 8000 |
| `inspectio_exercise.persistence` | Dedicated S3 persistence boundary | 8001 |
| `inspectio_exercise.notification` | Outcomes publish + query (Redis + S3 log) | 8002 |
| `inspectio_exercise.mock_sms` | Simulated provider + audit | 8080 |
| `inspectio_exercise.health_monitor` | On-demand audit vs S3 reconcile | 8003 |
| `inspectio_exercise.worker` | Shard worker (background loop placeholder + health) | 8004 |

**Infrastructure (not Python):** Redis container for hot outcomes cache; S3 (AWS or LocalStack) behind persistence.

## Install

```bash
cd nitzan_shinnies_inspectio_exercise
pip install -e ".[dev]"
```

## Run processes (CLI)

Console scripts (ports overridable via env vars in `inspectio_exercise/cli.py`):

```bash
inspectio-api
inspectio-persistence
inspectio-notification
inspectio-mock-sms
inspectio-health-monitor
inspectio-worker
```

Or `uvicorn` directly, e.g. `uvicorn inspectio_exercise.api.app:app --host 0.0.0.0 --port 8000`.

## Docker Compose

Starts **Redis** plus all Python services (build from repo root containing this directory):

```bash
docker compose up --build
```

## Tests

```bash
pytest
```

## Status

Skeleton only: **`GET /healthz`** on each service; business routes return **501** until implemented per plan documents.
