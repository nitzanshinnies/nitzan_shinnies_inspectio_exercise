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
| `inspectio_exercise.worker` | Shard scheduler (500ms tick, mock SMS, persistence, outcomes notify) | 8004 |
| `frontend/` (nginx) | Operational / demo UI — static assets + reverse proxy to API | 3000 → 80 |

**Infrastructure (not Python):** Redis container for hot outcomes cache; object storage is accessed only through the **persistence** service (local directory or AWS S3).

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

**Public API env (defaults match default ports above):** `PERSISTENCE_SERVICE_URL` (`http://127.0.0.1:8001`), `NOTIFICATION_SERVICE_URL` (`http://127.0.0.1:8002`), `TOTAL_SHARDS` (`256`, **must match every worker** — same value on API and all worker processes or pending keys and ownership will disagree).

### Worker env (`inspectio-worker`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOSTNAME` | `worker-0` (local) | StatefulSet-style name; trailing digits → pod index for shard ownership (`plans/SHARDING.md`). |
| `TOTAL_SHARDS` | `256` | Same formula as API when writing pending keys. |
| `SHARDS_PER_POD` | `256` | Contiguous shard range per pod. |
| `PERSISTENCE_SERVICE_URL` | `http://127.0.0.1:8001` | HTTP persistence microservice (no direct S3 from worker). |
| `MOCK_SMS_URL` | `http://127.0.0.1:8080` | `POST /send` target. |
| `NOTIFICATION_SERVICE_URL` | `http://127.0.0.1:8002` | `POST /internal/v1/outcomes` after durable terminal write. |
| `INSPECTIO_WORKER_TICK_SEC` | `0.5` | Wakeup interval (plans/CORE_LIFECYCLE.md). |
| `INSPECTIO_WORKER_PERSISTENCE_READ_RETRIES` | `5` | Bounded retries on transient persistence errors (`plans/RESILIENCE.md` §5). |
| `INSPECTIO_WORKER_PERSISTENCE_READ_BACKOFF_SEC` | `0.05` | Initial backoff; exponential per attempt. |
| `INSPECTIO_WORKER_TERMINAL_LOOKBACK_HOURS` | `6` | How far back (UTC hourly prefixes) the worker scans `state/success/` and `state/failed/` for **idempotent** reconciliation (duplicate pending vs existing terminal). Older terminals are not visible to this logic—increase the value if you must reconcile long-lived orphans (more `list_prefix` work per due message). |
| `INSPECTIO_WORKER_NOTIFY_RETRIES` | `3` | Outcome publish retries. |
| `INSPECTIO_WORKER_NOTIFY_BACKOFF_SEC` | `0.05` | Initial notify backoff. |

**Worker behavior notes**

- **Invalid `payload` at send time** (e.g. `to` / `body` not strings after a concurrent or manual S3 edit): the worker **deletes** the pending object (best-effort), **drops** in-memory scheduler state, and logs a warning — it does not spin forever on the heap.
- **Idempotency / scan cost:** Reconciliation lists hourly prefixes under success/failed for the lookback window **before** calling mock SMS when a message is due. Under very large buckets or long lookback, that is **O(lookback × list_prefix)** per check; tune `INSPECTIO_WORKER_TERMINAL_LOOKBACK_HOURS` accordingly.
- **`shouldFail` (mock SMS):** optional JSON field on `POST /messages` / `POST /messages/repeat` (alias **`shouldFail`**). When true, it is stored on the pending **`payload`** and the worker forwards it to mock SMS `POST /send` so attempts fail deterministically (`plans/MOCK_SMS.md`).

**Message routes (see `plans/REST_API.md`):** `POST /messages` — JSON `body` (required), `to` optional (default `+10000000000`), optional **`shouldFail`** (boolean). `POST /messages/repeat?count=N` — same JSON body as `/messages`, reused **`N`** times; response includes **`messageIds`** (and **`accepted`**). `GET /messages/success|failed` — optional **`limit`** (default **100**, e.g. `?limit=100`). Demo/operational UI is a **separate frontend container** (not served by this API).

### Persistence service backend (local dev vs AWS)

The HTTP routes are unchanged; **`build_persistence_backend()`** picks a **`PersistencePort`** plugin from the environment (`plans/LOCAL_S3.md` §5, `SYSTEM_OVERVIEW.md` §1.3).

| Mode | When it is selected | Required env |
|------|---------------------|--------------|
| **Local** (file tree) | `INSPECTIO_PERSISTENCE_BACKEND=local`, **or** implicit if **`LOCAL_S3_ROOT`** is set and backend is not forced to AWS | **`LOCAL_S3_ROOT`** — directory for `root/<s3-key>` files |
| **AWS** (S3) | `INSPECTIO_PERSISTENCE_BACKEND=aws`, **or** implicit if **`INSPECTIO_S3_BUCKET`** or **`S3_BUCKET`** is set (and no `LOCAL_S3_ROOT` / explicit local) | Bucket name; standard **`AWS_*`** credentials and optional **`AWS_REGION`** / **`AWS_DEFAULT_REGION`**; optional **`AWS_ENDPOINT_URL`** (e.g. LocalStack) |

Optional tuning: **`INSPECTIO_S3_CONNECT_TIMEOUT_SEC`**, **`INSPECTIO_S3_READ_TIMEOUT_SEC`**, **`INSPECTIO_S3_MAX_RETRY_ATTEMPTS`**.

**Local dev** from this directory:

```bash
export LOCAL_S3_ROOT="$(pwd)/.local-s3"
# optional: export INSPECTIO_PERSISTENCE_BACKEND=local
inspectio-persistence
```

Object files appear as **`LOCAL_S3_ROOT/<s3-key>`** (e.g. `state/pending/shard-0/<messageId>.json`). The repo includes **`.local-s3/`** with **`.gitkeep`**; other files there are **gitignored**.

**Production-shaped AWS** example:

```bash
export INSPECTIO_PERSISTENCE_BACKEND=aws
export INSPECTIO_S3_BUCKET=your-bucket
export AWS_REGION=us-east-1
inspectio-persistence
```

## Docker Compose

Starts **Redis**, all Python services, and the **web** UI (nginx on host port **3000** proxying `/messages` and `/healthz` to the API — `plans/REST_API.md` §3.0). **`TOTAL_SHARDS` is set the same on `api` and `worker`** so compose stacks do not rely on matching defaults alone. Build from the directory containing `docker-compose.yml`:

```bash
docker compose up --build
```

Open **http://localhost:3000** for the demo UI, or call the API directly at **http://localhost:8000**.

## Tests

Layout follows **`plans/TESTS.md`**: `tests/unit/`, `tests/integration/`, `tests/e2e/`. **Integration and e2e** still include **skipped** cases (worker bootstrap harness, multi-component flow, some notification/API outcome wiring) — see `pytest` markers and `tests/integration/README.md`; those are **outside** the worker + mock SMS implementation track until enabled.

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

- **Implemented (core exercise path):** public API message submission + outcomes proxy, **persistence** service (local + AWS backends), **notification** + Redis, **mock SMS** (`POST /send` + audit), **worker** (shard discovery, retries, terminal writes, outcome publish). **`GET /healthz`** on each service.
- **Implemented:** **`inspectio-health-monitor`** runs **`plans/HEALTH_MONITOR.md`** reconciliation: **`POST /internal/v1/integrity-check`** (optional **`graceMs`**), **`GET /internal/v1/integrity-status`**, **`GET /healthz`**. **Domain** matches **`tests/reference_spec.py`** where covered by **`pytest`**; expand skipped integration/e2e per **`plans/TESTS.md`** where noted.
