# V3 — Async pipeline implementation plan (agent-oriented)

This document is written for **autonomous coding agents** and humans implementing the **v3** architecture: **fully asynchronous** ingress, **SQS-centric** messaging on AWS ( **no Kinesis**; org may **explicitly deny** some services — verify before use), **in-memory persistence only** until a later phase, and a **performance north star** of **~10 000 `send()`-equivalent operations per second** aggregate under load (see **§2** for how “10k/s” is defined and measured).

**Normative precedence for agents**

1. **`plans/ASSIGNMENT.pdf`** (local; gitignored) — product contract: `send` / `newMessage` / `wakeup`, retry table, REST surface, NFRs.
2. **`plans/openapi.yaml`** — public HTTP shapes; update this **before** code when routes or fields change.
3. **This plan** — delivery order, invariants, and acceptance for the **v3 pipeline** only. It **does not** re-lock archived **v2** §29 FIFO-only ingest; v3 **replaces** that path for new code.
4. **`plans/V2_THROUGHPUT_POST_MORTEM.md`** — lessons (admit vs drain, driver design, timeouts); follow **`nitzan_shinnies_inspectio_exercise/.cursor/rules/inspectio-testing-and-performance.mdc`** and workspace rules for **in-cluster** AWS load tests and **bounded** Job / `kubectl wait` timeouts.
5. **Workspace `.cursor/rules/`** (antigravity repo) — e.g. **in-cluster load tests**, **EKS agent executes commands**, **restart stack before tests** where applicable.

**Out of scope for initial implementation waves (explicit)**

- Durable **S3 / journal** persistence and crash recovery (**ASSIGNMENT** AC5 deferred).
- **Kinesis**, **MSK**, or any streaming bus **not** available in the target account.
- Changing **ASSIGNMENT** method **signatures** (`send`, `newMessage`, `wakeup`) — wrappers/adapters allowed.

---

## 1) Target architecture (four layers)

### L1 — Single message origin (“edge”)

- **One deployable** serves **static frontend** (HTML/JS/CSS) and is the **only** browser entrypoint.
- Forwards **all** API operations to **L2** via **internal** URL (Kubernetes **Service** / later **ALB**). **No** direct browser calls to L2 bypassing L1 (CORS and security stay centralized on L1).
- **Coalescing rule:** UI or clients MUST NOT spam **N** identical HTTP calls for **N** copies. They issue **one** request with **`count`** (and later, **recipient list** when multi-recipient is modeled). L1 passes that **single** request downstream unchanged (no fan-out in the browser).

### L2 — API / admission tier (behind load balancer)

- **Horizontally scaled** **stateless** HTTP service(s) behind a **load balancer** (cluster **Service** `type: LoadBalancer` or **Ingress**/ALB on AWS).
- **Responsibilities:** validate **`openapi`** contracts, **auth placeholders** (if any), **idempotency key** acceptance, **enqueue** work to **L3** (SQS). **Do not** perform **`send()`** or heavy per-recipient work on the request thread beyond cheap validation and serialization.
- **Ordering:** **not** required across messages (**ASSIGNMENT** does not require global ingest order). Optimize for **throughput** and **availability**.

### L3 — Message fabric + broker logic (AWS **SQS**)

- **Queues:** use **Amazon SQS Standard** queues for **high aggregate throughput** unless a human explicitly locks **FIFO** for a subset. Prefer **multiple** queues (**sharding**) to avoid implicit hotspots and to allow **parallel `ReceiveMessage`** fleets.
- **Critical clarification:** SQS **does not** natively “split one message into **N** child messages.” The **broker** role is implemented as **application workers** (see **§3.3**) that consume **bulk-intent** messages and **produce** **per-unit** messages. This is still “async” and “brokered”; it is **not** a managed multi-cast feature.

### L4 — Workers

- **Expander / fan-out workers:** consume **bulk admit** messages; generate **per-send-unit** messages (unique **logical id** per unit); publish to **sharded send queues** using **batched** APIs (`SendMessageBatch`, ≤10 entries per call) with **parallelism across queues**.
- **Send workers:** consume **per-send-unit** messages; invoke the **`send(Message)`** path (HTTP to **mock-sms** or provider); maintain **in-memory** retry / schedule state per **§ASSIGNMENT**; expose hooks for **L5**.

### L5 — Persistence (stub in v3 phase 1)

- **No durable writes** in the first delivery waves. Optional **in-memory** ring buffer or **no-op** “persistence queue” consumer for **interface compatibility** only.
- **Later wave:** pluggable adapter (S3 journal, DynamoDB, etc.) **without** changing L2/L3 **envelope** shapes where possible.

---

## 2) Performance goal: “10 000 messages per second” (define and measure)

### 2.1 Meaning (locked for this plan)

- **Primary metric:** **aggregate rate of successful outbound `send()` calls** (or **mock-sms** `POST /send` equivalents) over a **steady window**, not **HTTP admissions/sec** alone.
- **Burst scenario:** a **single** user operation that targets **up to 10 000 recipients** should drive **~10 000 send invocations completed** within **~1 s** **once the pipeline is saturated** and downstream allows it. Treat this as an **SLO / stretch target**; agents must **measure** and report actual **p50/p99** latencies and **achieved RPS** using the **in-cluster** harness (**§8**).

### 2.2 Implications for design

- **Admission** may complete in **milliseconds** if it only enqueues **O(1)** bulk work; **send** path must run with **very high concurrency** (many worker replicas × non-blocking I/O × connection pools).
- **Per-unit messages** in SQS imply **receive → process → delete** capacity must match **10k/s**; **batch receive** and **horizontal scaling** of **send workers** are mandatory.
- **Response bodies:** avoid **O(N)** JSON arrays on hot paths (v2 post mortem); return **correlation / batch ids** and fetch details via **async** APIs if needed.

---

## 3) Concrete components and contracts

### 3.1 HTTP surface (L1/L2)

Maintain **`plans/openapi.yaml`** as source of truth. **Minimum** for parity with **ASSIGNMENT**:

| Method | Path | Notes |
|--------|------|--------|
| POST | `/messages` | Single send intent; fast **202** or **200** with **`messageId`** per **openapi**. |
| POST | `/messages/repeat` | **`count`** query param; **one** body; **must not** expand to **N** synchronous internal calls from L2. |
| GET | `/messages/success`, `/messages/failed` | **limit** ≤ 100 default per **ASSIGNMENT**; backed by **in-memory** indexes initially. |
| GET | `/healthz` | Liveness for k8s. |

**L1** may **proxy** these paths to L2 or **mount** the same app with a **path prefix**; agents must pick **one** documented approach and stick to it.

### 3.2 Idempotency

- Accept **`Idempotency-Key`** (header) or **`idempotencyKey`** (body) on **repeat** and **single** submit.
- **L2** dedupes **bulk** admission: duplicate keys within a TTL return the **same** **batchCorrelationId** without double-enqueueing.
- **Expander** dedupes: deterministic **`dedupeKey` → messageId** mapping **or** store seen keys **in memory** (phase 1); document **at-least-once** SQS behavior.

### 3.3 Suggested queue topology (agents implement names via env)

Use **Standard** queues unless waived.

| Queue purpose | Suggested env var | Producer | Consumer |
|---------------|-------------------|----------|----------|
| Bulk intents | `INSPECTIO_V3_BULK_QUEUE_URL` | L2 admission | Expander workers |
| Send shards **0..K-1** | `INSPECTIO_V3_SEND_QUEUE_URLS` (comma-separated) or prefix + K | Expander | Send workers |
| Persistence stub (optional) | `INSPECTIO_V3_PERSIST_QUEUE_URL` | Send workers | No-op / metrics worker |

**Sharding function:** `shard = stable_hash(messageId or batchUnitKey) % K` with **K** configurable (e.g. **16**–**64** to start).

### 3.4 Message envelopes (versioned JSON; agents define **Pydantic** models)

All SQS bodies MUST include:

- **`schemaVersion`** (int, start at **1**)
- **`traceId`** / **`batchCorrelationId`** where applicable

**BulkIntentV1 (L2 → expander queue):**

- `idempotencyKey`, `batchCorrelationId`, `count`, `body` (SMS payload), optional `recipients[]` (future), `receivedAtMs`, `clientMeta` (optional).

**SendUnitV1 (expander → send queues):**

- `messageId` (unique string), `body`, `attemptCount` (initial **0** or **1** per **ASSIGNMENT** mapping), `nextDueAtMs`, `batchCorrelationId`, `shard`, `receivedAtMs`.

Agents MUST add **`tests/unit`** for JSON round-trip and invalid payload rejection.

### 3.5 Scheduler / `wakeup()` mapping

- **ASSIGNMENT** requires **`wakeup()` every 500 ms**. Implement a **single leader** or **per-shard tick** using:

  - **asyncio** loop + `asyncio.sleep(0.5)` per worker process **with drift correction**, **or**
  - **APScheduler** / equivalent **inside** send worker processes,

  such that **due** messages are picked from **in-memory** structures **without** blocking SQS receive loops indefinitely.

- **Per-`messageId` exclusion:** only one concurrent **send / state mutation** per id (**ASSIGNMENT** concurrency rule). Use **`asyncio.Lock` per id** or **actor mailbox** pattern; **unit test** reentrancy / ordering.

---

## 4) Implementation phases (mergeable PRs)

Each phase: **tests first** (where feasible), then code, then **docs** (openapi, this plan cross-links only if needed). Follow **four-group imports**, **type hints**, **atomic functions** per workspace interview skill.

### Phase P0 — Repository wiring and guardrails

- **Goal:** pytest markers, CI/local **`pytest`**, **ruff**, **mypy** (if enabled), empty **v3** package namespace **`src/inspectio/v3/`** or agreed module split (**do not** break existing imports until cutover PR).
- **Tests:** marker compliance; import smoke.
- **Verify:** `pytest tests/unit -q` green.

### Phase P1 — OpenAPI + L2 admission skeleton (no SQS yet)

- **Goal:** FastAPI routes **stubbed** returning fixed ids; **openapi** updated; **Pydantic** request/response models.
- **Tests:** **httpx** `TestClient` **unit/integration** for each route.
- **Verify:** `pytest` + **openapi lint** if present.

### Phase P2 — SQS adapters + LocalStack

- **Goal:** `SqsClient` abstraction (**aioboto3**), **send/receive/delete** helpers, **retry on throttling** with jitter; **compose** LocalStack queue creation (init script or **terraform-less** shell).
- **Tests:** **integration** with LocalStack (docker); **unit** with **moto** where faster.
- **Verify:** compose up + `pytest -m integration` subset.

### Phase P3 — Expander worker

- **Goal:** consume **BulkIntentV1**, produce **SendUnitV1** to sharded queues; **SendMessageBatch** with **bounded concurrency**; metrics (**admitted**, **expanded**, **errors**).
- **Tests:** **unit** for sharding, batching math, idempotency; **integration** with LocalStack **producer → consumer** chain.
- **Verify:** end-to-end **one** bulk message → **N** visible messages across shards.

### Phase P4 — Send worker + mock-sms integration

- **Goal:** consume **SendUnitV1**, call **mock-sms**, implement **retry schedule** and **terminal** states **in memory**; expose outcomes API backing store.
- **Tests:** **unit** for schedule table; **integration** with **mock-sms** container; **e2e** compose: **repeat** → **all terminals** observable.
- **Verify:** `pytest -m e2e` (or marked subset) + manual **curl** smoke.

### Phase P5 — L1 static + proxy

- **Goal:** **Dockerfile** serves static files (**nginx** or **FastAPI StaticFiles**); proxies API to L2 Service; **docker-compose** wiring; **CORS** only on L1 if needed.
- **Tests:** **smoke** script or **e2e** hitting L1 only.
- **Verify:** browserless **curl** through L1 → L2 path works.

### Phase P6 — Kubernetes manifests + ConfigMap

- **Goal:** Deployments for **L1**, **L2**, **expander**, **send workers** (separate or combined binary with **`ROLE` env** — pick one and document); **Services**; **Secrets** for queue URLs; **resource requests** sane for small clusters.
- **Tests:** **none in-cluster in CI** unless you have a cluster; validate YAML with **`kubeconform`** if available.
- **Verify:** manual **`kubectl apply`** on dev cluster.

### Phase P7 — In-cluster performance harness

- **Goal:** extend **`scripts/full_flow_load_test.py`** (or **`v3` sibling script**) to report **send RPS** (from worker metrics or mock-sms audit endpoint), not only admission. **Job** YAML with **short** **`activeDeadlineSeconds`** per **`inspectio-testing-and-performance`** rule.
- **Tests:** **unit** for metric parsing.
- **Verify:** **in-cluster** run only for **AWS claims**; compose for **smoke**.

---

## 5) Agent execution rules (non-negotiable)

1. **Tests:** every new module gains **unit** tests; cross-boundary behavior gains **integration** or **e2e** tests. Use existing **`pytest` markers** (**`pyproject.toml`**).
2. **OpenAPI-first** for HTTP changes.
3. **No Kinesis**; **SQS** is the **only** required AWS messaging primitive unless the human approves **SNS/Lambda/DynamoDB** after quota check.
4. **AWS performance validation** only from **in-cluster** jobs; **no port-forward baselines** for throughput claims.
5. **Timeouts:** Job **`activeDeadlineSeconds`** and **`kubectl wait`** stay in the **minute** range for benchmarks unless explicitly documented otherwise (**post mortem** pitfalls).
6. **Do not** reintroduce **v2** **FIFO ingest** as the default in v3 paths without a written human waiver.
7. **Memory persistence:** document **data loss** on restart in **README** for v3 phase 1.

---

## 6) Acceptance checklist (v3 phase 1 — pipeline + memory)

- [ ] **L1** serves UI and proxies to **L2**; clients can use **single** **`/messages/repeat?count=N`**.
- [ ] **L2** enqueues **bulk** intent to SQS (**O(1)** HTTP work w.r.t. **N** aside from request size limits).
- [ ] **Expander** produces **N** **SendUnitV1** messages across **sharded** queues.
- [ ] **Send workers** achieve **mock** **`send`** for all units with **retry** semantics per **ASSIGNMENT** (in memory).
- [ ] **Outcomes** APIs return recent successes/failures per **openapi**.
- [ ] **`pytest`** **unit + integration (+ e2e where enabled)** pass locally.
- [ ] **Load script** documents how to measure **send RPS**; **AWS** numbers only from **in-cluster** run.
- [ ] **README** section: **architecture diagram** (text ok), **how to run compose**, **known limits** (no durability yet).

---

## 7) Optional AWS services (human confirms availability first)

Agents **must not** hard-depend on these without explicit approval:

- **SNS** (fan-out to multiple SQS — alternative to custom expander in some patterns)
- **Lambda** (SQS triggers)
- **DynamoDB** (idempotency or lease tables for leader election)
- **ElastiCache** (optional dedup / rate counters)

**Already verified unavailable for this org:** **Kinesis** (**SCP explicit deny** in one check — re-verify if policies change).

---

## 8) Observability and debugging

- **Structured JSON logs** with **`traceId`**, **`batchCorrelationId`**, **`messageId`**, **`shard`**, **`queueUrl`** (host only if needed).
- **Prometheus** metrics optional; minimum: **counters** logged periodically (**expanded**, **sent_ok**, **sent_fail**, **throttled**).
- **Distributed trace** hooks optional (OTel) — do not block P0–P4.

---

## 9) Revision history

| Date (UTC) | Note |
|------------|------|
| 2026-03-29 | Initial v3 async pipeline plan for agent implementation |
