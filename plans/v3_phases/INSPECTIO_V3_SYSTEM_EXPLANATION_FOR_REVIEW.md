# Inspectio v3 — Detailed system explanation (for review)

**Purpose:** Give architects and tech leads a single narrative of how the v3 pipeline works end to end, how **durable persistence** sits beside the hot path, how the system is **deployed and measured** on AWS, and where **known constraints** live. This document is descriptive; normative execution steps remain in the linked P12.x plans and runbooks.

**Audience:** Reviewers who may not have read the full plan tree or codebase.

---

## 1. What the system does (product-shaped summary)

Inspectio v3 is an **asynchronous messaging pipeline**:

1. **HTTP admission** accepts bulk send intents (`POST /messages`, `POST /messages/repeat?count=N`).
2. Intents are **enqueued** to a **bulk SQS queue** as `BulkIntentV1` envelopes.
3. An **expander** service long-polls the bulk queue, **fans out** each bulk message into many **`SendUnitV1`** messages, and routes each unit to one of **K sharded send queues** (hash of `messageId` mod **K**).
4. **Workers** (one deployment or process per send shard, scalable to many replicas per shard) long-poll their send queue, run the **domain `try_send` / retry schedule**, record **terminal outcomes** (success/failure) to **Redis**, and **delete** the SQS message when the send is terminal.
5. A thin **L1** layer exposes a demo UI and **proxies** the public API to L2.

**Persistence (when enabled)** runs **in parallel** with steps 1–4: structured **persistence events** are published to **dedicated persistence-transport SQS queues**, consumed by **persistence writer** processes that **flush** compressed batches to **S3** and advance **checkpoints**. Workers can **bootstrap recovery state** from S3 on startup so in-flight work aligns with what was durably recorded.

---

## 2. Logical architecture (control and data flow)

### 2.1 Main pipeline (no persistence detail)

```
Client → L1 (proxy + UI) → L2 (FastAPI)
                              ↓ enqueue BulkIntentV1
                         bulk SQS (inspectio-v3-bulk)
                              ↓ expander: fan-out + route
                         send SQS × K (inspectio-v3-send-0 … K-1)
                              ↓ worker per shard (N replicas possible)
                         try_send / retries / terminals
                              ↓
                         Redis (outcomes lists for GET /messages/success|failed)
                              ↓
                         DeleteMessage on send queue (after terminal + persistence hooks as configured)
```

**Important:** Expander **deletes** the bulk message only after **all** shard publishes for that bulk receipt succeed; otherwise the bulk message becomes visible again after visibility timeout.

### 2.2 Persistence path (feature-flagged)

When **`INSPECTIO_V3_PERSIST_EMIT_ENABLED=true`**, components call a **`PersistenceEventEmitter`** abstraction at key lifecycle points:

- **L2:** after bulk enqueue — `emit_enqueued` (so “admitted to bulk” is observable to persistence).
- **Worker:** on attempt results and terminal transitions — `emit_attempt_result`, `emit_terminal`.

The default implementation when persistence is off is a **no-op** emitter so behavior matches pre-persistence code paths.

**Transport layer (`inspectio.v3.persistence_transport`):**

- **`SqsPersistenceTransportProducer`** (and sharded variant) sends validated **`PersistenceEventV1`** JSON to SQS with **bounded retries**, optional **DLQ**, and explicit **backpressure** via **`INSPECTIO_V3_PERSIST_TRANSPORT_MAX_INFLIGHT`** (and durability mode semantics: best-effort vs strict).
- Events are routed to **one queue per persistence shard** when sharding is enabled (**P12.8**), analogous to send-shard routing but on a separate dimension (`persist-transport-{shard}`).

**Writer (`inspectio.v3.persistence_writer`):**

- Long-polls (with configured wait) persistence transport queue(s).
- **Buffers** events; flushes on **size** and **time** triggers (ConfigMap-tunable: flush interval, min batch events, checkpoint cadence).
- **Durability ordering:** segment object (compressed NDJSON) is written to **S3** **before** the **checkpoint** object is advanced — crash semantics assume readers use this ordering.
- After a successful flush, the writer **acks** transport messages (batch delete). Writer metrics and **`writer_snapshot {json}`** logs expose **receive**, **flush**, **S3 PUT**, **checkpoint**, and **ack/delete** timings and queue depth signals.

**Recovery (`inspectio.v3.persistence_recovery.bootstrap`):**

- On worker startup, optional **replay** from S3 segments rebuilds **pending / terminal exclusion** state so duplicates and retries remain safe relative to durable history.

### 2.3 Coupling between “admit fast” and “persist fast”

Even though persistence is “async,” **L2 and worker code paths `await` transport publish** in critical sections (e.g. after enqueue, before send-queue delete on some paths). That means **slow SQS publish**, **throttling**, or **`max_inflight` contention** can still **reduce HTTP-level admission RPS** and worker throughput when persistence is on. The **writer** can be healthy while the **producer side** or **network to SQS** limits the pipeline — this is a first-class architectural consideration documented in **P12.9 timing findings** (producer coupling / Plan B discussion).

---

## 3. AWS building blocks (typical EKS deployment)

| Concern | Technology | Notes |
|--------|------------|--------|
| Compute | **EKS** | Deployments for L1, L2 (`inspectio-api`), expander, workers (per send shard), persistence writers (per persistence shard), Redis |
| Queues | **SQS** | Bulk, K send queues, persistence transport queues (often 8-way sharded in perf configs), optional DLQs |
| Durable objects | **S3** | Segment blobs + checkpoint JSON under a defined prefix layout (`state/events/…`, `state/checkpoints/…`) |
| Fast state | **ElastiCache Redis** or in-cluster **Redis** | Outcome lists, idempotency helpers |
| Identity | **IRSA** | Task roles for API, workers, writers — policies must include SQS + S3 (and any iter4/WAL tables if used) |
| Observability | **CloudWatch** | SQS metrics; P12.9 hygiene uses **`NumberOfMessagesDeleted`** on **send** queues as a **completion proxy** alongside driver-reported admission |

**Networking:** S3 access from private subnets may use **VPC gateway endpoints** or NAT; endpoint choice affects latency and cost — captured in **`P12_9_EKS_S3_NETWORK_PATH.md`**.

---

## 4. Configuration surface (high level)

- **Feature flags:** `INSPECTIO_V3_PERSIST_EMIT_ENABLED` toggles whether real events hit SQS; must be changed with **full stack recycle** for comparable benchmarks.
- **Transport:** queue URLs, shard count, max attempts, backoff, batch sizes, **`max_inflight`**.
- **Writer:** flush interval, min batch for time-based flush, ack/delete concurrency, checkpoint frequency, observability snapshot cadence.
- **Worker recovery:** `INSPECTIO_V3_WORKER_RECOVERY_ENABLED`, shard binding.

Canonical keys live in **`src/inspectio/v3/settings.py`** and **`deploy/kubernetes/configmap.yaml`** (and EKS-applied ConfigMaps).

---

## 5. How performance and “persistence tax” are measured (P12.9)

**Goal:** Compare **persistence off** vs **on** under the **same** load shape, image tag, and (for apples-to-apples) **recycled** cluster state.

1. **Driver (in-cluster Job):** e.g. `scripts/v3_sustained_admit.py` — sustained `POST` load via L1/L2, reports **`offered_admit_rps`**, **`admitted_total`**, transient errors.
2. **Wall-clock files:** `off_start.txt` / `off_end.txt` and `on_*` bracket each leg.
3. **CloudWatch hygiene:** `scripts/v3_p12_9_iter3_rerun_hygiene.py` queries **`Sum`** of **`NumberOfMessagesDeleted`** across all **send** queues over a window derived from those timestamps (with preload/tail padding). It computes:
   - **Completion-side RPS** (combined average and peak across queues).
   - **R** = ratio of on/off **combined_avg_rps** (persistence-on completion as a fraction of persistence-off).
4. **Gates:** e.g. **R ≥ 52.66%** (promotion threshold), datapoint count symmetry, minimum active periods — documented in the script and **`ITERn_*_RESULTS.md`** artifacts.

**Interpretation for reviewers:** **R** is **not** “S3 throughput”; it reflects **end-to-end ability to complete work** visible at **send-queue deletes** while persistence is on, relative to off, under a fixed admission driver. **Writer snapshots** and **transport metrics** (`GET /internal/persistence-transport-metrics` when enabled) localize **where** time is spent (ack/delete vs S3 PUT vs producer backpressure).

---

## 6. Evidence-based performance narrative (short)

From **`P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md`** and writer metric peaks:

- **Writer-visible bottleneck** in sampled EKS runs was often **SQS ack/delete latency and depth**, not multi-second **S3 PUTs** (PUTs were comparatively smaller in those captures).
- **`receive_many` max duration** spikes often align with **long polling** on quiet queues, not necessarily a broken consumer.
- **Shard skew** (one persistence shard doing most flushes) can cap scaling unless **routing** spreads events.
- **Plan B** (weaker synchronous durability / async backup) is an **architectural** lever only with **explicit product and ops sign-off** — see decision records and Plan B doc.

---

## 7. Operational and organizational constraints

- **Benchmark discipline:** Throughput claims for AWS should come from **in-cluster** Jobs and service URLs, not laptop **port-forward** drivers.
- **Recycles:** After persistence-related ConfigMap or image changes, **restart all participating workloads** before benchmarking so in-memory state and env are clean (project runbook).
- **IAM vs SCP:** CLI principals may be powerful yet **Organizations SCPs** can still deny specific APIs (e.g. ECS, some quota APIs); designs should not **depend** on denied services without org alignment.

---

## 8. Code map (for deeper review)

| Area | Package / entry |
|------|------------------|
| L2 API | `inspectio.v3.l2` — `routes.py` (admission, internal metrics route) |
| L1 | `inspectio.v3.l1` |
| Expander | `inspectio.v3.expander` |
| Worker | `inspectio.v3.worker` — scheduler, persistence hooks |
| Persistence contracts | `PersistenceEventV1`, checkpoint schemas, replay helpers |
| Transport | `inspectio.v3.persistence_transport` |
| Writer | `inspectio.v3.persistence_writer` |
| Recovery | `inspectio.v3.persistence_recovery` |
| Settings | `inspectio.v3.settings` |

---

## 9. Canonical references (read next)

| Topic | Document |
|-------|----------|
| Architect spine + phased roadmap + living status | `ARCHITECT_PLAN_PERSISTENCE_AND_PLATFORM.md` |
| Timing interpretation + AI SE task order | `P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md` |
| Handoff index | `P12_9_AI_SE_HANDOFF_INDEX.md` |
| Session recovery / frozen images | `P12_9_SESSION_RECOVERY_PLAN.md` |
| Plan A tuning detail | `P12_9_AI_SE_PLAN_A_TRANSPORT_WRITER_TUNING.md` |
| Plan B / async backup | `P12_9_AI_SE_PLAN_B_ASYNC_BACKUP_ACK_CONTRACT.md`, `P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md` |
| Observability | `P12_9_AI_SE_PLAN_C_OBSERVABILITY.md` |
| Repo feature overview | Root `README.md` §V3 phases |

---

## 10. Revision note

This explanation is a **synthesis** for review. If implementation drifts (new services, changed contracts, or gate definitions), update the **numbered sections** here or add a short changelog at the top; keep **§9** pointers authoritative for execution detail.
