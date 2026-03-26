# Implementation phases (greenfield code)

This document orders delivery for the **`inspectio`** package described in **`NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** (especially **§9**, **§14**, **§24**, **§28**, **§29**). Each phase should be a **mergeable PR** (or a small stack of PRs) with tests and docs updated before moving on.

**Normative spec:** the blueprint wins on behavior; this file wins on **order** and **PR boundaries**.

### `v1_obsolete` boundary (agents — **hard**)

The tree **`v1_obsolete/`** is an **archived implementation**, not a dependency of the greenfield **`inspectio`** package.

- **Do not** add `import inspectio_exercise`, `from v1_obsolete…`, path hacks into **`v1_obsolete/project/src`**, or copy-paste v1 modules into **`src/inspectio/`**.
- **Do not** treat **`v1_obsolete/**`** tests (e.g. under **`v1_obsolete/project/tests`** or **`obsolete_tests`**) as the canonical suite to mirror 1:1; greenfield tests live under repo-root **`tests/`** per this file and **§28**.
- **May read** **`v1_obsolete/plans/*`** only when the blueprint explicitly cites a **trap** or **rejected** equivalence (e.g. **§2.3** “relative” retries vs **§6.2**). Prefer **this blueprint** + **`plans/openapi.yaml`** for behavior.
- **Mock SMS in Docker:** the **mock-SMS** service is whatever **root `docker-compose.yml`** declares (today that may build from archived paths for the **container image only**). **Do not** add a runtime **`import inspectio_exercise`** (or other **`v1_obsolete/project/src`** imports) in **`src/inspectio`** API/worker/notification code.

Same rule appears in blueprint **§29.11** (forbidden list).

---

## Agent readiness (*honest*)

| Tier | Phases | Ready for unattended agents? |
|------|--------|------------------------------|
| **A** | **P0–P2** | **High** — file paths, math, and codecs are fully specified in **§29.2** + **§6** / **§16–18**; few integration unknowns. |
| **B** | **P3–P5** | **Medium** — must wire **async** I/O, LocalStack/moto endpoints, and **§18.3** ordering; agents should **cite blueprint sections** in PRs and add integration tests before merging. |
| **C** | **P6** | **Medium–hard** — concurrency (**§20.3.1**, **§29.9**), state machine + journal interleaving; highest bug risk; prefer **human review** or a second agent pass focused on **TC-CON-***. |
| **D** | **P7–P8** | **Medium** — Redis list semantics, proxy error handling, snapshot/replay edge cases (**TC-REC-003**). |
| **E** | **P9–P10** | **Environment-dependent** — needs working **Docker**, often **AWS/EKS** credentials; agents cannot “finish” P10 without a real cluster and policy allow-list. |

**Bottom line:** no phase is “perfect” without the implementing agent **opening the cited blueprint sections** and the **OpenAPI** file. This doc gives **boundaries** and **verification hooks**; it does not replace reading **§15–§20** and **§29**.

**Blueprint §9 crosswalk (*corrected*):** **P3** = admission slice of **§9 Phase 1**; **P4–P5** = durability + consumer (**§9 Phase 1** ingest path + **§14** journal SoT); **P6** = **§9 Phase 2** scheduler; **P8** = **§9 Phase 3** snapshots; **P7** = **§9 Phase 4** read plane; **P10** = **§7** AWS + **§28.6** in-cluster load.

---

## Per-phase template (every P below)

Each phase includes:

- **Prerequisites** — prior phases that must be merged.
- **Read first** — blueprint §§ to open.
- **§29.2 touch rows** — copy/paste **verbatim** rows from **§29.2** (subset for this phase); **§29.3** for **P9** only. **Do not** add paths absent from **§29.2** unless the blueprint is amended.
- **Implement** — concrete behaviors (still normative to blueprint).
- **Do not** — scope guard (avoid **§29.11** and phase creep).
- **Exit criteria** — commands + **§28.8** **TC-** ids (minimum bar before next phase).

---

## Canonical §29.2 repository layout (*verbatim from blueprint*)

All application code under **`src/inspectio/`**:

| Path | Responsibility |
|------|------------------|
| `src/inspectio/__init__.py` | Package marker; **optional** `__version__` |
| `src/inspectio/settings.py` | **Pydantic `Settings`** loading **§29.4** |
| `src/inspectio/models.py` | **`Message`**, **`RetryStateV1`** (dataclasses or pydantic models) |
| `src/inspectio/scheduler_surface.py` | **`send`**, **`new_message`**, **`wakeup`** (**§25**) |
| `src/inspectio/domain/schedule.py` | `RETRY_OFFSET_MS`, `next_due_ms(arrival_ms, completed_send_count)` |
| `src/inspectio/domain/sharding.py` | `shard_for_message(message_id, total_shards)` per **§16.2** |
| `src/inspectio/ingest/schema.py` | `MessageIngestedV1` encode/decode (**§17.2**) |
| `src/inspectio/ingest/kinesis_producer.py` | API-side **PutRecords** |
| `src/inspectio/ingest/kinesis_consumer.py` | Worker-side poll + checkpoint (**§29.6**) |
| `src/inspectio/journal/records.py` | `JournalRecordV1` types + validation (**§18.2**) |
| `src/inspectio/journal/writer.py` | batch flush **§29.8** |
| `src/inspectio/journal/replay.py` | snapshot + tail replay (**§18.4**) |
| `src/inspectio/worker/main.py` | CLI / `asyncio.run` entry (**`inspectio-worker`**) |
| `src/inspectio/worker/runtime.py` | immediate queue, **`wakeup()`** loop, due set |
| `src/inspectio/worker/handlers.py` | apply ingest, run state machine, call **`send`** |
| `src/inspectio/sms/client.py` | **§19** httpx client |
| `src/inspectio/api/app.py` | FastAPI factory |
| `src/inspectio/api/routes_public.py` | **§15** routes only |
| `src/inspectio/notification/app.py` | FastAPI or Starlette for **§29.6** |
| `src/inspectio/notification/outcomes_store.py` | Redis **LPUSH** + **LTRIM** (**§5.2** keys) |

**Tests:** `tests/unit/...`, `tests/integration/...` mirroring the above. **`pyproject.toml`:** `packages = [{ include = "inspectio", from = "src" }]` (or equivalent).

---

## Canonical §29.3 deployable processes (*verbatim from blueprint*)

| Process | Module entry | Purpose |
|---------|--------------|---------|
| **`inspectio-api`** | `inspectio.api.app:app` | **§15** + Kinesis producer |
| **`inspectio-worker`** | `inspectio.worker.main:main` (create `main.py`) | consumer + scheduler |
| **`inspectio-notification`** | `inspectio.notification.app:app` | **§29.6** + Redis |

---

## P0 — Tooling and package skeleton

**Prerequisites:** none.

**Read first:** **§13**, **§29.2**, **§28.1–28.2**.

**§29.2 touch rows (verbatim):**

| Path | Responsibility |
|------|------------------|
| `src/inspectio/__init__.py` | Package marker; **optional** `__version__` |

**Also required (§29.2 tail + §29.13):** **`pyproject.toml`** (`packages = [{ include = "inspectio", from = "src" }]` or equivalent); **`tests/unit/...`**, **`tests/integration/...`** mirroring layout; **`deploy/docker/Dockerfile`** (single image for **§29.3** processes); pytest markers via **`pyproject.toml`** `[tool.pytest]` or **`pytest.ini`**.

**Implement**

- Editable install **`pip install -e ".[dev]"`**; package name **`inspectio`**, **`src/`** layout (**§29.2**).
- Single **Dockerfile** used later by **P9**; **`CMD`** overridden by compose.
- pytest markers: **`unit`**, **`integration`**, **`e2e`**, **`performance`** (**§28.2**).

**Do not** add scheduler, API routes, or AWS calls beyond optional dev deps.

**Exit criteria**

- `python -c "import inspectio"`
- `pytest --collect-only -q` succeeds.

---

## P1 — Pure domain (no I/O)

**Prerequisites:** **P0**.

**Read first:** **§4.2**, **§6.2**, **§16.2**, **§21**.

**§29.2 touch rows (verbatim):**

| Path | Responsibility |
|------|------------------|
| `src/inspectio/models.py` | **`Message`**, **`RetryStateV1`** (dataclasses or pydantic models) |
| `src/inspectio/domain/schedule.py` | `RETRY_OFFSET_MS`, `next_due_ms(arrival_ms, completed_send_count)` |
| `src/inspectio/domain/sharding.py` | `shard_for_message(message_id, total_shards)` per **§16.2** |

**Implement**

- **`RETRY_OFFSET_MS`** and **`next_due_ms`** per **§6.2** (absolute from **`arrivalMs`**).
- **`shard_for_message`** per **§16.2** (SHA-256 → first 4 bytes BE → `% TOTAL_SHARDS`**).
- **`Message`**, **`RetryStateV1`** fields per **§4.1–4.2**.

**Do not** import boto3, httpx, or FastAPI in domain modules.

**Exit criteria**

- **`pytest -m unit`** — all **TC-DOM-001–008**, **TC-SHA-001–004** (**§28.8**).

---

## P2 — Ingest schema and journal codec

**Prerequisites:** **P0** ( **P1** can land in parallel).

**Read first:** **§17.2**, **§18.1–18.2**, **§29.5**.

**§29.2 touch rows (verbatim):**

| Path | Responsibility |
|------|------------------|
| `src/inspectio/ingest/schema.py` | `MessageIngestedV1` encode/decode (**§17.2**) |
| `src/inspectio/journal/records.py` | `JournalRecordV1` types + validation (**§18.2**) |

**Implement**

- **`MessageIngestedV1`** JSON round-trip; **`bodyHash`** = lowercase hex SHA-256 UTF-8 **`payload.body`** (**§29.5**).
- **`JournalRecordV1`** discriminated by **`type`**; validate required **`payload`** keys (**§18.2** table).
- Parse gzip NDJSON bytes → list of records (**§18.1**) — **keep helpers inside `journal/records.py`** (or private submodules under `journal/` **only** if you split files; **do not** add a new top-level path not listed in **§29.2** without updating the blueprint).

**Do not** call Kinesis or S3 in unit tests (fixtures only).

**Exit criteria**

- **`pytest -m unit`** — **TC-JNL-001–005**.

---

## P3 — API admission (Kinesis only, no `send`)

**Prerequisites:** **P0**, **P1** (for **`shardId`**), **P2** (for ingest record encoding).

**Read first:** **§15**, **§16.4**, **§17.1**, **§29.4** (API vars), **§29.10**, **`plans/openapi.yaml`**.

**§29.2 touch rows (verbatim):**

| Path | Responsibility |
|------|------------------|
| `src/inspectio/settings.py` | **Pydantic `Settings`** loading **§29.4** |
| `src/inspectio/api/app.py` | FastAPI factory |
| `src/inspectio/api/routes_public.py` | **§15** routes only |
| `src/inspectio/ingest/kinesis_producer.py` | API-side **PutRecords** |

**Implement**

- **`POST /messages`**, **`POST /messages/repeat`**, **`GET /healthz`** per **OpenAPI** + **§15**; **202** bodies match schema.
- **`GET /messages/success|failed`**: return **`501`** with stable JSON **or** omit routes until **P7** — if omitted, document in README; **prefer** registering routes that return **501** so OpenAPI paths exist (**agents:** pick one approach and keep **OpenAPI** as source of truth).
- **`PutRecords`** with partition key **`f"{shardId:05d}"`**; batch ≤ **500** per AWS limit.
- Route handlers **must not** `await` **`send()`** or worker activation (**TC-API-008**).

**Do not** implement **`Idempotency-Key`** / **409** (**§29.10**).

**Exit criteria**

- **`pytest -m "unit or integration"`** — **TC-API-001–005**, **TC-API-008**.
- Validate OpenAPI: e.g. **`npx @redocly/cli lint plans/openapi.yaml`** (optional CI) or manual diff.

---

## P4 — S3 journal writer (flush policy)

**Prerequisites:** **P0**, **P2**.

**Read first:** **§5.1**, **§18.1**, **§29.4** (bucket, prefix), **§29.8**.

**§29.2 touch rows (verbatim):**

| Path | Responsibility |
|------|------------------|
| `src/inspectio/journal/writer.py` | batch flush **§29.8** |

**Implement**

- Buffered lines; flush when **time ≥ INSPECTIO_JOURNAL_FLUSH_INTERVAL_MS** OR **lines ≥ INSPECTIO_JOURNAL_FLUSH_MAX_LINES** (**§29.8**).
- S3 keys per **§5.1**; **`recordIndex`** monotonic per **`shardId`**.
- Retry on throttling with backoff (**TC-FLT-002**).

**Do not** advance Kinesis checkpoints ( **P5** ).

**Exit criteria**

- Integration tests against **moto** or LocalStack S3 + **TC-FLT-002**.

---

## P5 — Kinesis consumer + checkpoint + ingest durability

**Prerequisites:** **P2**, **P3**, **P4** (consumer must persist **§18.3** lines via writer).

**Read first:** **§17.3–17.5**, **§18.3**, **§29.4**, **§29.6**, **§29.7** (template A only for ingest path).

**§29.2 touch rows (verbatim):**

| Path | Responsibility |
|------|------------------|
| `src/inspectio/ingest/kinesis_consumer.py` | Worker-side poll + checkpoint (**§29.6**) |
| `src/inspectio/worker/main.py` | CLI / `asyncio.run` entry (**`inspectio-worker`**) |
| `src/inspectio/worker/handlers.py` | apply ingest, run state machine, call **`send`** |

*(In P5, implement **ingest + journal + checkpoint** only inside **`handlers.py`**; leave full state machine / **`send`** to **P6**.)*

**Implement**

- Poll Kinesis; deserialize **`MessageIngestedV1`**; Redis **`SET NX`** dedupe **§17.4**; append **§29.7** sequence **A** (`INGEST_APPLIED` → `DISPATCH_SCHEDULED`) via journal writer; **then** persist checkpoint **§29.4** key layout.
- **Single-worker default** (**§29.6**): one process may own all stream shards locally.

**Do not** run full **`send`** / retry state machine unless **P6** merged (stub handler may enqueue to in-memory dict for P5-only demo — **prefer** no fake scheduler: stop after journal + checkpoint).

**Exit criteria**

- **TC-STR-001–003**, integration test for **§28.4** item **2** (journal visible before checkpoint advance).
- **TC-REC-001** with synthetic journal lines acceptable if consumer not yet feeding full replay.

---

## P6 — Scheduler runtime + `scheduler_surface`

**Prerequisites:** **P1**, **P2**, **P4**, **P5** (ingest + journal path live).

**Read first:** **§6**, **§19–20**, **§25**, **§29.7** (templates B–E), **§29.9**.

**§29.2 touch rows (verbatim):**

| Path | Responsibility |
|------|------------------|
| `src/inspectio/scheduler_surface.py` | **`send`**, **`new_message`**, **`wakeup`** (**§25**) |
| `src/inspectio/worker/main.py` | CLI / `asyncio.run` entry (**`inspectio-worker`**) |
| `src/inspectio/worker/runtime.py` | immediate queue, **`wakeup()`** loop, due set |
| `src/inspectio/worker/handlers.py` | apply ingest, run state machine, call **`send`** |
| `src/inspectio/sms/client.py` | **§19** httpx client |

**Implement**

- **`new_message`** / immediate queue / **`wakeup`** **500 ms**; due messages **`nextDueAtMs <= now`**; per-**`messageId`** **`asyncio.Lock`** (**§29.9**).
- State transitions **§6.2**; journal per **§29.7**; **`send`** → **§19** httpx.
- **`inspectio.scheduler_surface`**: **`send`**, **`new_message`**, **`wakeup`** (**§25** import path).

**Do not** break **TC-API-008**; do not list S3 success prefixes for outcomes.

**Exit criteria**

- **TC-SUR-001–005**, **TC-CON-001–002**, **TC-DOM-007–008**, **TC-FLT-003** (SMS timeout path).

---

## P7 — Notification service + Redis outcomes + GET proxy

**Prerequisites:** **P3**, **P6** (terminals published).

**Read first:** **§5.2**, **§15.3**, **§29.6**, **`plans/openapi.yaml`**.

**§29.2 touch rows (verbatim):**

| Path | Responsibility |
|------|------------------|
| `src/inspectio/notification/app.py` | FastAPI or Starlette for **§29.6** |
| `src/inspectio/notification/outcomes_store.py` | Redis **LPUSH** + **LTRIM** (**§5.2** keys) |
| `src/inspectio/api/routes_public.py` | **§15** routes only |

**Implement**

- Redis keys **`inspectio:outcomes:success`** / **`failed`** (**§5.2**); **`LPUSH` + `LTRIM`**; newest-first for **`LRANGE`**.
- Internal routes + public GET proxy exactly as **OpenAPI**; **`finalTimestamp`** / **`finalTimestampMs`** mapping documented if names differ (must match public **§15.3** JSON).

**Do not** scan S3 terminal prefixes for hot GET (**§29.11**).

**Exit criteria**

- **TC-OUT-001–003** (as applicable), **TC-API-006–007**.

---

## P8 — Snapshots + replay completeness

**Prerequisites:** **P4**, **P5**, **P6**.

**Read first:** **§14** (Phase 3 row), **§18.4**.

**§29.2 touch rows (verbatim):**

| Path | Responsibility |
|------|------------------|
| `src/inspectio/journal/replay.py` | snapshot + tail replay (**§18.4**) |
| `src/inspectio/journal/writer.py` | batch flush **§29.8** |

*(Periodic **snapshot** emission uses **`journal/replay.py`** for format/load logic and **`journal/writer.py`** for S3 puts / timers — both paths already listed in **§29.2**; do not add **`journal/snapshot.py`** unless the blueprint is amended.)*

**Implement**

- Load **`latest.json`** + replay tail **`recordIndex > lastRecordIndex`** (**§18.4**).
- Periodic snapshot (**`INSPECTIO_SNAPSHOT_INTERVAL_SEC`**).

**Do not** truncate journal without an ops policy (document **informative** gap in README if not implemented).

**Exit criteria**

- **TC-REC-002**, **TC-REC-003**.

---

## P9 — Compose + E2E smoke

**Prerequisites:** **P3**, **P6**, **P7** minimum (full happy path).

**Read first:** **§26**, **§29.13**, **§28.5**, **§29.3**.

**§29.2 / §29.3 touch (no new `src/` paths):** wire **§29.3** module entries to containers:

| Process | Module entry | Purpose |
|---------|--------------|---------|
| **`inspectio-api`** | `inspectio.api.app:app` | **§15** + Kinesis producer |
| **`inspectio-worker`** | `inspectio.worker.main:main` (create `main.py`) | consumer + scheduler |
| **`inspectio-notification`** | `inspectio.notification.app:app` | **§29.6** + Redis |

**Also:** **`docker-compose.yml`** (add the three services + shared **`deploy/docker/Dockerfile`** build), **`README.md`**.

**Implement**

- Three services, shared image **§29**, env wiring **§29.13** table; **`depends_on`** LocalStack healthy + redis + mock-sms; **uvicorn** / **`python -m`** commands must target the **§29.3** entries above **verbatim**.
- Smoke: **POST /messages** → wait terminal → **GET** sees row (script or **TC-E2E-001**).

**Do not** claim **§28.6** AWS numbers from laptop compose.

**Exit criteria**

- `docker compose up -d --build` exits 0; smoke script documented in README.

---

## P10 — AWS (EKS) + in-cluster load

**Prerequisites:** **P9** (or equivalent images).

**Read first:** **§7**, **§8**, **§26**, **§28.6**, workspace rule *inspectio* in-cluster load tests.

**§29.2 touch rows:** *none* (infra / ops only). **§29.3** container names and module entries **must not** change without a blueprint bump.

**Infra touch list:** `deploy/kubernetes/` (or Helm), **`scripts/`** load driver **or** in-cluster Job YAML (see **`deploy/kubernetes/`** when present).

**Implement**

- IRSA, stream, bucket, Redis, ingress; no static keys in ConfigMaps (**§7.2**).
- Load job runs **inside** VPC/EKS; results from Job logs.

**Do not** use **`kubectl port-forward`** as proof of throughput (**workspace rule**).

**Exit criteria**

- README runbook + **TC-PERF-002** if performance is claimed.

---

## Dependency graph

```text
P0 → P1 ─┬→ P3 → P5 → P6 → P7 → P9 → P10
          │
P0 → P2 ──┼→ P4 ─┘
          └→ (P2 before P5; P4 before P5)
P6,P7 → P8 (snapshots; can parallel P7 tail if replay tested without notification)
```

**Recommended linear order for a single agent:** **P0 → P1 → P2 → P4 → P3 → P5 → P6 → P7 → P8 → P9 → P10**  
(*P4 before P3* avoids API-only PR without a writer if you want strict layering; **P3 before P5** is mandatory so consumer has records to read.)

---

## Checklist per PR (all phases)

1. README env table / commands if new variables (**§26**).
2. **`plans/openapi.yaml`** updated before code if HTTP shape changes (**§29.13**).
3. Tests name **TC-** ids (**§28.8**).
4. No **§29.11** forbidden patterns.
