# Inspectio exercise

Distributed **SMS retry scheduler** per `plans/` (S3 truth, workers, notification + Redis, mock SMS, health monitor).

## Layout (skeleton)

| Python package / app | Role | Default port |
|---------------------|------|--------------|
| `inspectio_exercise.api` | Public REST API | 8000 |
| `inspectio_exercise.health_monitor` | On-demand audit vs S3 reconcile | 8003 |
| `inspectio_exercise.mock_sms` | Simulated provider + audit | 8080 |
| `inspectio_exercise.notification` | Outcomes publish + query (Redis + S3 log) | 8002 |
| `inspectio_exercise.persistence` | Dedicated S3 persistence boundary | 8001 |
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
inspectio-health-monitor
inspectio-mock-sms
inspectio-notification
inspectio-persistence
inspectio-worker
```

Or `uvicorn` directly, e.g. `uvicorn inspectio_exercise.api.app:app --host 0.0.0.0 --port 8000`.

## Docker Compose

Starts **Redis** plus all Python services (build from repo root containing this directory):

```bash
docker compose up --build
```

## Tests

Layout follows **`plans/TESTS.md`**: `tests/unit/`, `tests/integration/`, `tests/e2e/` (integration/e2e are mostly placeholders until features exist).

**TDD:** Canonical behavior is documented in **`tests/reference_spec.py`** (with notes tying to **`plans/`**). **`inspectio_exercise.domain`** should match that spec; stubs raise **`NotImplementedError`** until implemented — **`pytest tests/unit`** stays **red** until domain, REST contract, and related gates pass.

Smoke / wiring: **`GET /healthz`** (liveness) passes with the skeleton; REST contract tests and domain tests fail until implementation lands (see **`plans/TESTS.md` §1.1–§1.2**).

```bash
pytest
pytest tests/unit
pytest -m unit
pytest -m integration
pytest -m e2e
```

Dev deps include **`httpx`**, **`pytest-asyncio`**, and **`ruff`** (lint + format).

## Lint

```bash
pip install -e ".[dev]"
ruff check src tests
ruff format src tests   # apply formatting
```

Configuration lives in **`pyproject.toml`** (`[tool.ruff]`). CI should run `ruff check` (and optionally `ruff format --check`).

## Status

Skeleton: **`GET /healthz`** on each service; business routes return **501** until implemented per plan documents. **Domain** package: implement to satisfy **`tests/reference_spec.py`** (see **`plans/TESTS.md` §4**).
