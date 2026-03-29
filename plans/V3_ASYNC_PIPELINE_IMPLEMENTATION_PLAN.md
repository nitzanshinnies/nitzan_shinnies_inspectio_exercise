# V3 — Async pipeline implementation plan (agent-oriented)

This document is written for **autonomous coding agents** and humans implementing the **v3** architecture: **fully asynchronous** ingress, **SQS-centric** messaging on AWS (**no Kinesis**; org may **explicitly deny** some services — verify before use), **in-memory (non-durable) state** until a later phase, and a **performance north star** of **~10 000 `send()` invocations per second** aggregate under load (see **§2**).

---

## 0) Assignment (ASSIGNMENT.pdf) traceability

**Source:** `plans/ASSIGNMENT.pdf` (local; gitignored). **Do not change** the three method **signatures** from the PDF; **wrappers and internal adapters** are allowed (see **§3.6**).

| PDF clause | Requirement | V3 plan handling | Phase-1 status |
|------------|-------------|------------------|----------------|
| **Arrival** | `newMessage(Message)` when each SMS enters | Map to: after **SendUnitV1** exists, worker runs **`new_message`-equivalent** (immediate **attempt #1** per retry table). **Bulk HTTP** → **one** `BulkIntentV1` → expander creates **N** units → each unit enters the worker path as **one** logical arrival. | **Pass** (by construction) |
| **Tick** | `wakeup()` every **500 ms** (**exact**), concurrent with arrivals | **§3.5** — per-process or per-shard timer; must not starve **ReceiveMessage**. | **Pass** |
| **send** | `boolean send(Message)` thread-safe | **§3.6** — internal **`try_send(message) -> bool`** (or injectable callable); **public** Java-style signature preserved in **`assignment_surface`** module if required; **void** Python body allowed **only** as **thin wrapper** that returns **`bool`** to scheduler. | **Pass** (adapter) |
| **Retry table** | **#1** at **0 s** (inside `newMessage`); **#2–#6** at **0.5 s, 2 s, 4 s, 8 s, 16 s** after **initial arrival**; **#6** fail → discard, **failed** | **§3.7** — deadlines are **absolute epoch ms from first arrival** (`receivedAtMs`), not gaps between attempts. | **Pass** |
| **REST** | `POST /messages`, `POST /messages/repeat?count=N`, `GET` success/failed **limit=100** | **§3.1**; keep **`plans/openapi.yaml`** aligned. | **Pass** |
| **Repeat response** | Returns **list of messageIds** **or a summary** | **Performance:** prefer **summary** (`batchCorrelationId`, `count`, optional sampling) if **openapi** and **human** accept; **full `messageIds`** remains **ASSIGNMENT-valid** and may be required for **e2e** tests that poll by id — **pick one per release** and document in **openapi**. | **Configurable** |
| **Outcomes** | **Last 100** each; sort by **most recent attempt** time; fields: **`messageId`**, **`attemptCount`**, **`finalTimestamp`**, **reason** if failed | **§3.8** — response shapes must match **openapi** **Outcome** schemas. | **Pass** |
| **NFR throughput** | Design for **tens of thousands/sec** | **§2** | **Target / measure** |
| **NFR contention** | Minimize locks / hot spots | Sharded queues, per-`messageId` lock only (**§3.5**). | **Pass** |
| **NFR idempotency** | Reasonable if **`newMessage` twice** for same payload | **§3.2** + expander dedupe. | **Pass** |
| **NFR crash** | Restart continues from **persisted** state (**S3** in PDF) | **Deferred** — **§1 out of scope**; document as **known gap** in **README** (required by PDF deliverables). | **Deferred (AC5)** |
| **NFR time** | Not **before** due; not **significantly later** under load | **§6** acceptance + tests with clock control. | **Pass** |
| **README** | Data structures, sync, complexity, gaps, AWS run, **S3 layout/schema** | **§6** — include **S3 schema as “planned / phase 2”** when persistence is absent. | **Pass** (honest gaps) |
| **AWS** | Runs on **AWS** with provided credentials | **§4** P6–P7 — **EKS/ECS/EC2** acceptable. | **Pass** |

---

## 1) Normative precedence for agents

1. **`plans/ASSIGNMENT.pdf`**
2. **`plans/openapi.yaml`** — update **before** code when HTTP shapes change; description should point at **this plan**.
3. **This plan** — v3 pipeline only. **v1/v2 code and specs are removed from the repo** — do not restore FIFO-ingest v2 as a default path.
4. **`nitzan_shinnies_inspectio_exercise/.cursor/rules/inspectio-testing-and-performance.mdc`** and workspace **`.cursor/rules/`** — **in-cluster** load tests, **bounded** timeouts, **EKS agent executes commands**, etc.
5. **Optional:** **`plans/V2_THROUGHPUT_POST_MORTEM.md`** — **historical** measurement notes only; **not** normative for v3 implementation.

**Out of scope for initial waves (explicit)**

- **Durable S3 persistence** and **AC5** restart recovery (PDF requires S3 — **re-enable in a later wave**; see **§0**).
- **Kinesis** / MSK / unavailable streaming.
- **Changing** PDF method **signatures** — **not allowed**; **adapters** are.
- **mock-sms** HTTP service — **not used** in phase 1 (**§3.6**).

---

## 2) Target architecture (five layers)

### L1 — Single message origin (“edge”)

- **One deployable** serves **static frontend** (HTML/JS/CSS); **optional plus** per PDF.
- Proxies **all** API calls to **L2** (internal **Service** / **Ingress**). Browsers do **not** call **L2** directly (centralize **CORS** / TLS on **L1**).
- **Coalescing:** **one** `POST /messages/repeat?count=N` with **one** JSON body — **no** **N** parallel duplicate posts from the UI for load tests.

### L2 — API / admission (behind load balancer)

- Stateless **FastAPI** (or equivalent) behind **LB**; validates **openapi**; **enqueue** **BulkIntentV1** to SQS; **no** per-recipient **`send()`** here.
- **Ordering:** PDF does **not** require global cross-message order; optimize for **throughput** and **correct per-`messageId` scheduling**.

### L3 — SQS + broker (**expander** workers)

- **Standard** queues + **sharding** (env-driven **K** send queues) unless human locks **FIFO**.
- SQS **cannot** split one message into **N**; **expander** workers implement **broker** logic (**BulkIntentV1** → **N × SendUnitV1**).

### L4 — **Send** workers (scheduler + `send`)

- Consume **SendUnitV1**; run **`newMessage` / `wakeup` / `send`** semantics **in process** per **§3.5–3.7**; **void / bool `send`** per **§3.6**.
- Publish **terminal events** to **OutcomesStore** (**§3.8**).

### L5 — Persistence (stub)

- Phase 1: **no S3 journal**; optional **no-op** persist queue for interface only.
- Later: S3 layout per PDF (**§0** table) without breaking queue envelopes where possible.

---

## 3) Performance goal (“10k/s”)

### 3.1 Meaning (locked for this plan)

- **Primary metric:** **completed in-process `send` attempts per second** (count calls into the **`try_send` / `send` path** after dequeue), measured over a steady window.
- **Burst:** one logical **`count=10 000`** submit should drive **~10 000** such completions within **~1 s** when the fleet is sized for it — **SLO / stretch**; **report p50/p99** and achieved RPS via **Phase P7** harness (**in-cluster** for AWS claims).

### 3.2 Design implications

- **Admission** should be **O(1)** w.r.t. **N** (bulk enqueue + **summary** response if chosen).
- **SQS** **receive → handle → delete** must sustain target RPS (**batch receive**, many replicas).
- **Void `send`** removes HTTP latency from **`send`**; bottlenecks become **CPU**, **scheduler**, **SQS APIs**.

---

## 4) Concrete contracts

### 4.1 HTTP surface (ASSIGNMENT §Minimal API)

| Method | Path | Notes |
|--------|------|--------|
| POST | `/messages` | Body = message payload; returns **`messageId`** (or **202** + id per **openapi**). |
| POST | `/messages/repeat` | Query **`count`**; **one** body; **ids list or summary** — **openapi** is authoritative. |
| GET | `/messages/success`, `/messages/failed` | **`limit`** default **100**; outcome fields per PDF + **openapi**. |
| GET | `/healthz` | Probes (**PDF** ext / ops). |

### 4.2 Idempotency (PDF **NFR**)

- **`Idempotency-Key`** header or body field on **single** and **repeat**.
- **L2:** duplicate key → **same** `batchCorrelationId`, **no** second bulk enqueue (TTL-bounded).
- **Expander:** at-least-once SQS → **dedupe** so **N** units are not doubled for the same logical bulk.

### 4.3 Queue topology (env)

| Purpose | Env (suggested) | Producer | Consumer |
|---------|-----------------|----------|----------|
| Bulk | `INSPECTIO_V3_BULK_QUEUE_URL` | L2 | Expander |
| Send shards `0..K-1` | `INSPECTIO_V3_SEND_QUEUE_URLS` or prefix + **K** | Expander | Send workers |
| Persist stub | `INSPECTIO_V3_PERSIST_QUEUE_URL` (optional) | Send worker | No-op |

**Shard:** `stable_hash(messageId) % K`.

### 4.4 Message envelopes (**Pydantic** + **tests/unit**)

- **`schemaVersion`**, **`traceId`**, **`batchCorrelationId`** where relevant.

**BulkIntentV1:** `idempotencyKey`, `batchCorrelationId`, `count`, `body`, `receivedAtMs` (server clock at L2), optional metadata.

**SendUnitV1:** `messageId`, `body`, **`receivedAtMs`** (= **initial arrival** for **retry table**), `batchCorrelationId`, `shard`; **`attemptsCompleted`** (int, **0** before first `send`) or equivalent — **agents must document** whether counting starts at **0** or **1** and align **terminal** at **6 failed attempts** per PDF.

### 4.5 Scheduler / `wakeup()` (**PDF** concurrent with `newMessage`)

- **`wakeup` every 500 ms** per worker process (or **elected leader** per shard — choose **one** strategy, document **split-brain** risk for phase 1).
- **Do not** block the **receive loop** indefinitely; use **non-blocking** schedule scan or **handoff** to a **timer task**.
- **Per-`messageId` mutex:** at most **one** concurrent **`send` / state mutation** per id (**PDF**).

### 4.6 `send` and **`boolean` vs void** (phase 1, **no mock-sms**)

- **PDF:** `boolean send(Message)`.
- **Implementation:** keep a **`try_send(message) -> bool`** (or injectable **`Callable[[Message], bool]`**) used by **retry / terminal** logic. A **`send(message) -> None`** wrapper may **only** call **`try_send`** and **discard** the bool **if** no caller needs it — **scheduler must branch on `bool`**.
- **Default `try_send`:** return **`True`** (success) with **empty body** for throughput experiments; tests inject **`False`** for retry paths.
- **Later:** replace **`try_send`** body with real provider I/O **without** changing **PDF** signatures at the **public** boundary.

### 4.7 Retry timeline (**absolute** from **`receivedAtMs`**)

| Attempt | Latest due (ms after **initial arrival**) |
|---------|---------------------------------------------|
| #1 | **0** (run **inside** the **`new_message` path** when the unit is first handled) |
| #2 | **500** |
| #3 | **2000** |
| #4 | **4000** |
| #5 | **8000** |
| #6 | **16000** |

- **Never** fire **before** `nextDueAt` (PDF **NFR**).
- After **6-th failed `try_send`** → **discard** + **`failed`** terminal (PDF).
- **Unit tests** with **fake clock** are **mandatory** for this table.

### 4.8 Outcomes index (**multi-replica L2**)

- **Problem:** terminals are produced on **send workers**; **GET /messages/success|failed** is served by **L2**.
- **Phase 1 requirement:** a **shared ephemeral store** any **L2** replica can read — e.g. **Redis** (container in compose / ElastiCache on AWS) holding **ring buffers** of terminals, **or** a tiny **dedicated outcomes service**. **Pure in-memory dict inside L2** is **invalid** with **>1** L2 pod unless **sticky sessions** (avoid).
- **Workers** **push** terminal records (**messageId**, **attemptCount**, **finalTimestamp**, **reason**) to that store; **L2** **reads** for **GET** (sort **most recent first**, cap **limit**).

---

## 5) Implementation phases (mergeable PRs)

Each phase: **tests first** where feasible; **four-group imports**; **type hints**; **atomic** functions.

| Phase | Goal | Verify |
|-------|------|--------|
| **P0** | Package layout **`src/inspectio/v3/`** (or agreed tree), pytest markers, **assignment_surface** module with **PDF**-shaped stubs | `pytest tests/unit -q` |
| **P1** | **L2** routes + **openapi** sync; **BulkIntent** enqueue stub | `TestClient` tests |
| **P2** | **SQS** client (**aioboto3**), LocalStack queues, throttling backoff | `pytest -m integration` |
| **P3** | **Expander** | bulk → **N** **SendUnitV1** across shards |
| **P4** | **Send worker**: **§4.6–4.7**, **OutcomesStore** write, **`wakeup`** loop | unit + integration + **e2e** compose |
| **P5** | **L1** static + proxy | curl via **L1** only |
| **P6** | **Kubernetes** manifests, ConfigMap / Secrets for URLs | `kubectl` on dev cluster |
| **P7** | **Load harness** + Job YAML: **send RPS**, **in-cluster** only for AWS claims; **short** deadlines per **inspectio-testing-and-performance** | metrics match **§3.1** |

---

## 6) Agent rules (non-negotiable)

1. **Unit + integration + e2e** per **`pyproject.toml`** markers; new code → new tests.
2. **OpenAPI-first** for HTTP.
3. **SQS** required; **no Kinesis**; optional **SNS/Lambda/DynamoDB** only after human confirms quotas.
4. **AWS performance** claims → **in-cluster Job** only (**no port-forward** baseline).
5. **Bounded** **`activeDeadlineSeconds`** / **`kubectl wait`** (minutes, not hours) unless explicitly overridden in YAML comments.
6. **README** must list **PDF deliverables**: structures, sync, complexity, **gaps** (incl. **no AC5** in phase 1), AWS run, **future S3 schema**.
7. **No v1/v2:** do **not** import, copy, or reference removed legacy trees in **code or tests** (**`.cursor/rules/inspectio-implementation-no-legacy.mdc`**).

---

## 7) Acceptance checklist

### 7.1 PDF checklist (phase 1 — honest)

- [ ] **AC1** `newMessage` / equivalent: **attempt #1** immediate; later attempts **scheduled** per **§4.7**.
- [ ] **AC2** `wakeup` drives **due** retries on **~500 ms** cadence **without** global lock contention.
- [ ] **AC3** **6** failed **`try_send`** → **failed** terminal, discarded from active schedule.
- [ ] **AC4** **GET** outcomes last **100** with required fields (**§0**).
- [ ] **AC5** restart / **S3** recovery — **deferred**; **documented** in **README** as **not yet implemented**.
- [ ] **AC6** runs on **AWS** with provided credentials (**P6–P7** evidence).

### 7.2 V3 pipeline

- [ ] **L1** → **L2** proxy only for browser clients.
- [ ] **Repeat** = **one** HTTP request; **expander** creates **N** units.
- [ ] **Sharded** SQS **send** queues + **batch** publish/consume.
- [ ] **Outcomes** consistent across **L2** replicas (**§4.8**).
- [ ] **Load** script reports **send RPS**; AWS numbers from **in-cluster** run only.

---

## 8) Observability

- Structured logs: **`traceId`**, **`batchCorrelationId`**, **`messageId`**, **`shard`**.
- Counters: **expanded**, **send_ok**, **send_fail**, **sqs_throttle**.

---

## 9) Optional AWS services (confirm before hard dependency)

**SNS**, **Lambda**, **DynamoDB**, **ElastiCache** — **human approval**. **Kinesis** was **SCP-denied** in one check; re-verify if policies change.

---

## 10) Revision history

| Date (UTC) | Note |
|------------|------|
| 2026-03-29 | Initial v3 async pipeline plan for agent implementation |
| 2026-03-29 | Drop mock-sms; void / bool `send` adapter (**§3.6** predecessor) |
| 2026-03-29 | Coherence pass: **ASSIGNMENT §0** traceability, **§4.7** retry table, **§4.8** outcomes, **five** layers, PDF **AC** / **README** deliverables, fix internal **§** refs |
| 2026-03-29 | Remove v1/v2 trees from repo; normative precedence without legacy specs; agent rule **#7** |
