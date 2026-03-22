# TESTS.md - Detailed Plan (Section 10)

This document expands **Section 10** of [`plans/PLAN.md`](PLAN.md): **testing** for the SMS retry scheduler exercise. It aligns with [`plans/SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md), [`plans/CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md), [`plans/SHARDING.md`](SHARDING.md), [`plans/RESILIENCE.md`](RESILIENCE.md), [`plans/REST_API.md`](REST_API.md), [`plans/MOCK_SMS.md`](MOCK_SMS.md), [`plans/HEALTH_MONITOR.md`](HEALTH_MONITOR.md), and [`plans/NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md).

**Enumerated checklist:** [`plans/TEST_LIST.md`](TEST_LIST.md) (full test case IDs, edge cases, 9.1 companion).

## 1) Goals

- Prove **deterministic** behavior where the spec is deterministic (sharding, retry delays, ownership, **500ms** tick semantics).
- Prove **lifecycle correctness** (pending → success / terminal failed) and **no broad S3 listing** for recent outcomes.
- Prove **resilience**: owned-shard bootstrap restores due work from persisted `nextDueAt` after restart; **malformed** pendings skipped safely; optional **transient persistence errors** during bootstrap retried with bounded backoff ([`RESILIENCE.md`](RESILIENCE.md) §5).
- Prove **idempotency**: duplicate activations / duplicate API behavior must not create **duplicate terminal side effects** for the same `messageId` ([`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md) §6.2, [`REST_API.md`](REST_API.md) §5.2).
- Prove the **persistence service boundary**: API and workers do **not** bypass the dedicated persistence layer ([`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md)).
- Keep tests **fast**, **repeatable**, and **isolated**—no reliance on real AWS or real SMS.

### 1.1 Strict TDD policy (this repo)

- **Unit tests assert final behavior** from the plans (`tests/reference_spec.py`, `REST_API.md`, etc.), not stub responses (**501** skeleton handlers, **`NotImplementedError`** domain stubs) as an acceptable steady state.
- Tests **stay failing** until the corresponding feature is implemented; do not rewrite tests to match placeholders just to go green.
- **`tests/fakes.RecordingPersistence`** is for **spies** in integration tests; **`PersistencePort`** contract tests target **`src/`** once a real adapter exists (see §4.10).
- **`GET /healthz`** liveness is exercised in `tests/unit/test_healthz.py` (**`status` + `service`**); that **passes** with the skeleton. **Readiness** (deps OK) is optional per [`REST_API.md`](REST_API.md) §3.5—add dedicated tests when you extend the contract.
- **`mock_sms.config.MOCK_SMS_CONTRACT_COMPLETE`**: set to **`True`** only when the mock SMS contract (`tests/unit/test_mock_sms_contract.py`) is fully green with production code.

### 1.2 Tests-first branch (no implementation yet)

A branch may land **only** the **expanded unit test suite** (and keep **`src/`** as skeletons / stubs). That is valid workflow: **`pytest` is expected to be red** on that branch. A **separate** branch/series of commits **implements** production code until `tests/unit` passes. Do not add production logic on the tests-first branch just to satisfy the suite.

## 2) Out of scope (for this exercise)

- Production load/chaos testing at tens-of-thousands RPS.
- Multi-region S3 semantics, IAM policy proofs.
- Kubernetes e2e in CI (optional locally); **in-process** or **docker-compose** style tests are enough if documented.
- **TOTAL_SHARDS migration / remapping** ([`SHARDING.md`](SHARDING.md) §6.2): treat as a **manual migration** test plan only if you implement remapping; not required for baseline CI.

## 3) Tooling assumptions (recommended)

- **pytest** + **pytest-asyncio** for async units and integration hooks.
- **Ruff** (`ruff check src tests`, `ruff format`) — configured in **`pyproject.toml`**; **`pre-commit`** runs **`ruff`** + **`ruff-format`** on commit (see **README.md** § Lint).
- **time control**: fake clocks or injectable `now()` / monotonic time source so wakeup, `nextDueAt`, and **`state/success|failed/<yyyy>/<MM>/<dd>/<hh>/...`** path generation are not flaky.
- **S3 simulation**: **moto** or **LocalStack**, **or** the **file-backed mock S3** behind the persistence service interface (preferred for speed if available) — spec + dedicated provider tests: [`LOCAL_S3.md`](LOCAL_S3.md).
- **HTTP**: **httpx** `AsyncClient` + **ASGI lifespans** for in-process API tests; **respx** or transport doubles for outbound mock-SMS calls.
- **Spies / fakes**: assert the persistence interface is the only module performing S3-like I/O from API/worker code paths.

## 4) Unit tests (required areas)

### 4.1 Sharding and ownership

Cover (see [`SHARDING.md`](SHARDING.md)):

- **Stable shard id**: same `messageId` + `TOTAL_SHARDS` → same `shard_id` (deterministic hash, e.g. sha256-based mapping).
- **Range mapping**: given `pod_index` and `shards_per_pod`, owned shard set matches `range(pod_index * shards_per_pod, (pod_index + 1) * shards_per_pod)`.
- **`HOSTNAME` → `pod_index`**: if implementation derives ordinal from `HOSTNAME` ([`PLAN.md`](PLAN.md) §4), cover expected parsing for representative names (e.g. `worker-0`, StatefulSet DNS patterns).
- **Out-of-range guard**: messages whose `shard_id` is not owned must be **ignored** for processing decisions (no writes to foreign pending prefixes); optionally assert **skip diagnostics** are emitted ([`SHARDING.md`](SHARDING.md) §4).

### 4.2 Retry timeline and `nextDueAt`

Cover [`plans/PLAN.md`](PLAN.md) timeline relative to **previous attempt** time:

- For each failure at `attemptCount` **before** terminal, computed `nextDueAt` matches: **+0.5s, +2s, +4s, +8s, +16s** for attempt **#2 … #6** (align `attemptCount` convention with [`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md) §4).
- **Terminal**: when **`attemptCount == 6`**, **no further** scheduling—transition to **failed** terminal key layout ([`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md) §4.2).
- **While `attemptCount < 6`**: failed send updates pending in place with new `nextDueAt` ([`PLAN.md`](PLAN.md) §5).

### 4.3 Wakeup loop: due selection, ordering, and **500ms** cadence

Cover [`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md) §4:

- On a tick at time `T`, only messages with **`nextDueAt <= T`** are eligible.
- **Ordering**: due work is consumed in **earliest-`nextDueAt`-first** order (Min-Heap–compatible semantics).
- **Concurrency**: multiple due messages in one tick can be dispatched concurrently **without** breaking idempotency or terminal transitions.
- **Cadence**: with an injectable clock, **`wakeup()`** (or equivalent) advances on **`exactly every 500ms`** tick—assert tick count ↔ simulated time relationship (e.g. 10 ticks ⇒ **5s** elapsed) and that post-bootstrap processing matches [`RESILIENCE.md`](RESILIENCE.md) §2.

### 4.4 S3 state transitions and **date-partitioned** terminal keys

Test persistence orchestration (via fakes/moto):

- **Success**: pending no longer authoritative; **success** key under `state/success/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json` ([`SHARDING.md`](SHARDING.md) §2.2); terminal JSON **`status`** is **`success`** ([`PLAN.md`](PLAN.md) §3).
- **Retry**: pending under `state/pending/shard-<shard_id>/` updated with new `attemptCount` / `nextDueAt`; JSON **`status`** remains **`pending`** ([`PLAN.md`](PLAN.md) §3).
- **Terminal failure**: **failed** key under `state/failed/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`; body **`status`** is **`failed`**.
- **Clock injection**: for a fixed “now”, assert path segments **`yyyy/MM/dd/hh`** match **UTC** per [`PLAN.md`](PLAN.md) §3 (including **DST** non-issues in UTC and **year/month rollover**).

### 4.5 Recent outcomes (notification service + API)

Cover [`REST_API.md`](REST_API.md) §4, [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md), and [`PLAN.md`](PLAN.md) §7:

- **Bounded hot-store streams** (via notification service; Redis plugin uses LIST cap per [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md) §4) at least **`max(limit)`** (≥ **100** when `limit` omitted; **~10k** cap).
- **Publish path:** after durable terminal S3 write, worker **publishes** to the notification service → **`state/notifications/...`** put + **hot store** update (Redis: `LPUSH`/`LTRIM` or ZSET equivalent).
- **API `GET` path:** handlers query the **notification service** only (**no Redis client in API**)—spy: **no** `state/success/` or `state/failed/` **list** on those requests.
- **Hydration:** on notification service restart, **up to `HYDRATION_MAX`** newest rows load from S3 **into the hot store**—assert order and cap ([`RESILIENCE.md`](RESILIENCE.md) §7).
- **Integration:** **`OUTCOMES_STORE_BACKEND=memory`**, **fakeredis** behind **`RedisOutcomesHotStore`**, **embedded Redis**, or **Testcontainers Redis** for publish/query/hydration tests.
- **`limit`**: optional query param, **default 100**; invalid `limit` → **4xx**; clamp policy if implemented ([`REST_API.md`](REST_API.md) §3.3–3.4).

### 4.6 Mock SMS contract (worker client or mock app)

Cover [`MOCK_SMS.md`](MOCK_SMS.md):

- **`2xx`** ⇒ success path; **any `5xx`** ⇒ failed send / retry path (worker must not branch correctness on specific **5xx**).
- **`shouldFail: true`** (if worker forwards it in tests) ⇒ **always `5xx`**.
- **Failure kinds**: optionally assert the mock (when exercised) can return **`503`** vs **`500`/`502`** per module constants—worker still retries either ([`MOCK_SMS.md`](MOCK_SMS.md) §3.3).
- **`RNG_SEED`** set in mock module ⇒ intermittent outcomes **reproducible** for tests.
- **Send integrity / audit** ([`MOCK_SMS.md`](MOCK_SMS.md) §8): each handled `POST /send` produces an audit row (**JSONL** on stdout and/or **`GET /audit/sends`**); assert **expected sequence** (per `messageId` / optional `attemptIndex`) in unit/integration; E2E may reconcile **send counts** vs terminal outcomes where feasible.

### 4.7 REST handlers and contracts

Cover [`REST_API.md`](REST_API.md):

- `POST /messages`: reject empty/malformed `body` / `to`; stable **4xx** body shape (**machine-readable code + message**) where implemented ([`REST_API.md`](REST_API.md) §5.1–5.3).
- `POST /messages/repeat?count=…`: same body as **`POST /messages`**, reused **`count`** times; reject invalid `count`; enforce **upper bound**; response reflects **`N`** distinct `messageId`s when successful.
- `GET /messages/*`: invalid `limit` handling (exercise: **`?limit=100`** defaults when omitted).
- `GET /healthz`: returns **2xx** quickly (lightweight liveness; may run as integration smoke).

### 4.8 Idempotency and duplicate handling

Cover [`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md) §6.2 and §8 checklist item 8:

- **Duplicate `newMessage` / activation** for the same `messageId` must not create duplicate **terminal** keys or inconsistent state.
- **Replay** after success or terminal failed: no second terminal write; side effects remain **monotonic**.
- If API allows logically duplicate submissions, behavior must be **defined and tested** (reject vs dedupe vs idempotent accept) per [`REST_API.md`](REST_API.md) §5.2.

### 4.9 Activation ordering (API-first, attempt #1)

Cover [`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md) §3:

- **Durable pending** exists under `state/pending/shard-<shard_id>/<messageId>.json` **before** attempt #1.
- **Attempt #1** runs with **0s delay** after valid activation (`attemptCount=0`).

### 4.10 Persistence service boundary

Cover [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) §1–2:

- API and worker modules under test must use the **persistence interface**, not an ad-hoc S3 client (static review optional; **spy** in tests preferred where practical).

## 5) Integration tests (required)

### 5.1 Persistence service + S3 simulation

- All reads/writes exercised in the test go through the **dedicated persistence service** (no ad-hoc S3 client in app code under test).
- **List/get** operations in bootstrap only target **owned** `state/pending/shard-<shard_id>/` prefixes ([`RESILIENCE.md`](RESILIENCE.md) §3).

### 5.2 Worker bootstrap / resilience

Cover [`RESILIENCE.md`](RESILIENCE.md) §3–4 and [`SHARDING.md`](SHARDING.md) §5:

- Seed pending keys with varied `nextDueAt`; bootstrap restores **min-heap-compatible** due ordering.
- **Malformed** pending JSON: **skip**, no crash; invalid-record metric/log hook if exposed.
- **Terminal safety**: objects only under `state/success/...` or `state/failed/...` must not be re-enqueued as pending ([`RESILIENCE.md`](RESILIENCE.md) §4.3).
- **Idempotency cache**: if used, **rehydrate or reset** from persistence on startup so stale cache cannot block recovery ([`RESILIENCE.md`](RESILIENCE.md) §4.3).

### 5.3 API → pending → activation path

- `POST /messages` creates pending under the **correct** `shard-<shard_id>/` for the assigned `messageId`.
- Harness runs worker attempt #1: mock SMS **`2xx`** → success path; **`5xx`** → retry state in pending with updated `nextDueAt`.

### 5.4 Bootstrap: transient persistence failures

Cover [`RESILIENCE.md`](RESILIENCE.md) §5:

- Simulate **transient read failures** during owned-shard scan: implementation **retries** with bounded backoff; after recovery, bootstrap completes and due work is correct.
- (Optional) exceed threshold → **startup-degraded** signal if implemented.

### 5.5 Scale / ownership recomputation (lightweight)

- Under a changed **`shards_per_pod` or replica count** configuration in a **single-process multi-worker test**, each “pod” instance only processes **currently owned** shards ([`SHARDING.md`](SHARDING.md) §6.1). Deep multi-pod e2e optional.

### 5.6 Health monitor (mock audit vs S3)

Cover [`HEALTH_MONITOR.md`](HEALTH_MONITOR.md):

- **Unit:** pure reconciliation on **fixture** audit JSON + **fixture** S3 object map—**terminal success** must imply **≥1** mock **`2xx`**; **terminal failed** vs **audit** per documented counting rule; **no** duplicate success+failed.
- **Integration / compose:** run **mock SMS** + **persistence/S3** + **health monitor**; **`GET /healthz`** returns **2xx** without running full reconcile; **`POST`** **integrity-check** after a deterministic scenario returns **2xx** + `ok`; inject **phantom** audit or **stub S3** drift and assert **`POST`** returns **non-2xx** or violation JSON per §4.2.

## 6) End-to-end tests (strongly recommended)

Compose **API + worker scheduler + persistence (mock S3) + mock SMS HTTP** where feasible:

- **Happy path**: SMS **`2xx`** → **success** terminal key; **`GET /messages/success`** reflects outcome per cache rules.
- **Retry path**: SMS **`5xx`** then **`2xx`** → pending updates until success.
- **Send integrity (recommended):** where the real mock HTTP service runs, validate **mock audit log** vs expected attempts (e.g. **`GET /audit/sends`** or container **stdout JSONL** per [`MOCK_SMS.md`](MOCK_SMS.md) §8).
- **Terminal failure**: SMS always **`5xx`** until **`attemptCount == 6`** → **failed** key; **`GET /messages/failed`** reflects outcome per cache rules.
- **Restart**: persist mid-retry pending; **restart worker** / rerun bootstrap → retry resumes per **`nextDueAt`** ([`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md) §8 item 7).
- **`POST /messages/repeat?count=N`** (body reused **`N`** times): **`N`** distinct `messageId`s and **`N`** durable pendings.
- **`GET /healthz`**: **2xx** from API process.
- **Health monitor (when compose includes it):** **`GET /healthz`** **2xx** (liveness); after steady-state, **`POST` integrity-check** **2xx** ([`HEALTH_MONITOR.md`](HEALTH_MONITOR.md) §4); optional negative **`POST`** with induced drift.

## 7) Determinism and flakiness guardrails

- **Do not** depend on real wall-clock sleep for correctness tests; use injected time or short timeouts only for optional smoke.
- **Mock SMS**: **`RNG_SEED`** or stub HTTP client for precise sequences.
- **IDs**: fixed UUIDs in golden tests where helpful.

## 8) Traceability (requirements → coverage)

Map suites to spec checklists:

- **Architecture / persistence boundary**: `SYSTEM_OVERVIEW.md` §1–2.
- **Sharding**: `SHARDING.md` §8 checklist.
- **Lifecycle / 500ms / concurrency / idempotency**: `CORE_LIFECYCLE.md` §8 checklist.
- **Bootstrap / degraded startup / terminal safety**: `RESILIENCE.md` §8 checklist.
- **REST / recent outcomes**: `REST_API.md` §8 checklist, `NOTIFICATION_SERVICE.md` §10 validation checklist.
- **Mock SMS**: `MOCK_SMS.md` §11 checklist (includes audit/integrity).
- **Health monitor**: `HEALTH_MONITOR.md` §7 checklist; **TC-HM-*** in [`TEST_LIST.md`](TEST_LIST.md).

## 9) Automation expectations (exercise)

- **Unit** suite runs on every change (fast, no Docker dependency if possible).
- **Integration** suite may use moto, LocalStack, or file-backed mock **in process**.
- Document any **skipped** tests (e.g. optional K8s e2e, TOTAL_SHARDS migration) with reason.

## 10) Validation checklist (this testing plan)

Section 10 testing work is complete when:

1. Unit tests cover **sharding**, **ownership**, **`HOSTNAME` mapping** (if applicable), **retry timeline**, **500ms cadence**, **wakeup due selection**, and **terminal rules**.
2. Tests prove **pending / success / failed** key paths including **date-partitioned** terminal keys under an injectable clock.
3. **Recent outcomes** follow [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md): **publish** path, **GET** without broad terminal-prefix listing, and **hydration** after notification service restart.
4. **Idempotency** tests exist for duplicate activation / replay and **no duplicate terminal side effects**.
5. **Persistence boundary** is enforced (no silent bypass) in tests or documented static review with spot-check spies.
6. **Integration** tests cover bootstrap, **malformed** pendings, and (where implemented) **transient persistence retry** during startup.
7. At least one **multi-component** test covers **API → pending → worker → mock SMS → terminal state → notification publish → `GET` outcomes** and **`/repeat`** with **`N > 1`**.
8. At least one test proves **bootstrap after restart** restores due work from owned pending shards.
9. **`GET /healthz`** smoke is present for the API.
10. How to run suites is documented in **README** (or **`CONTRIBUTING`**) once implementation exists.
11. **Mock SMS send audit** ([`MOCK_SMS.md`](MOCK_SMS.md) §8) is exercised: audit records + **JSONL** (and **`GET /audit/sends`** when enabled), aligned with **TC-SMS-12** / **TC-E2E-10** in [`TEST_LIST.md`](TEST_LIST.md).
12. **Health monitor** reconciliation is covered per **§5.6** and **TC-HM-*** ([`HEALTH_MONITOR.md`](HEALTH_MONITOR.md)).

## 11) Conceptual test layers

```mermaid
flowchart TB
  Unit[Unit tests pure logic sharding timeline cache]
  Integ[Integration persistence service mock S3 bootstrap]
  E2E[E2E API worker mock SMS terminal paths]

  Unit --> Integ
  Integ --> E2E
```
