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

**Public API env (defaults match default ports above):** `PERSISTENCE_SERVICE_URL` (`http://127.0.0.1:8001`), `NOTIFICATION_SERVICE_URL` (`http://127.0.0.1:8002`), `TOTAL_SHARDS` (`256`, must align with workers).

**Message routes (see `plans/REST_API.md`):** `POST /messages` — JSON `body` (required), `to` optional (default `+10000000000`). `POST /messages/repeat` — JSON `count` (required), optional `to` / `body` (defaults `+10000000000` / `load-test`). `GET /messages/success|failed` — optional `limit` and `to` query (defaults documented in the plan).

### Local file-backed S3 (dev)

The persistence service writes through **`LocalS3Provider`** when **`LOCAL_S3_ROOT`** is set (`plans/LOCAL_S3.md`). This repository includes **`.local-s3/`** at the project root; object files under it are **gitignored** (only **`.local-s3/.gitkeep`** is tracked so the directory exists in clones).

From this directory:

```bash
export LOCAL_S3_ROOT="$(pwd)/.local-s3"
inspectio-persistence
```

Then create keys via **`POST /internal/v1/put-object`** or by running the API against this persistence service — files appear as **`LOCAL_S3_ROOT/<s3-key>`** (e.g. `state/pending/shard-0/<messageId>.json`).

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

Dev deps include **`httpx`**, **`pytest-asyncio`**, **`pre-commit`**, and **`ruff`** (lint + format).

## Lint

On each commit, **`pre-commit`** runs **`ruff`** (with fixes) and **`ruff-format`** via **`.pre-commit-config.yaml`**. Install the hook once per clone:

```bash
pip install -e ".[dev]"
pre-commit install
```

Manual checks (same rules as the hook):

```bash
ruff check src tests
ruff format src tests   # apply formatting
```

Configuration lives in **`pyproject.toml`** (`[tool.ruff]`).

## Status

Skeleton: **`GET /healthz`** on each service; business routes return **501** until implemented per plan documents. **Domain** package: implement to satisfy **`tests/reference_spec.py`** (see **`plans/TESTS.md` §4**).
