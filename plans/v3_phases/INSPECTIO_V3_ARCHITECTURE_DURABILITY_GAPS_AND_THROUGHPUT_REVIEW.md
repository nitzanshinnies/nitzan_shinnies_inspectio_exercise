# Inspectio v3 — Architecture, why messages look “missing,” and persistence throughput (for review)

**Purpose:** A single document reviewers can use to understand **how the system is wired**, **why S3/admit verification can disagree**, and **what throughput was actually measured with persistence on**.  

**Companion:** High-level narrative and links: `INSPECTIO_V3_SYSTEM_EXPLANATION_FOR_REVIEW.md`.

---

## 1. Architecture (concise)

### 1.1 Main pipeline (send path)

Traffic enters **L1** → **L2**. L2 enqueues **`BulkIntentV1`** to **bulk SQS**. The **expander** consumes bulk messages, fans out **`SendUnitV1`** records to **K sharded send queues** (routing uses `hash(messageId) % K` — **not** randomized). **Workers** consume from **their** send queue, execute **`try_send`** / retries, write **outcomes** to **Redis**, and **delete** the send-queue message after a **terminal** outcome (with persistence hooks as configured).

**Important:** “Admitted” HTTP success only means the bulk intent reached **bulk SQS**. Downstream **expand → send → try_send → terminal** is **asynchronous** and can lag arbitrarily if workers or expanders are slower than admission.

### 1.2 Persistence path (parallel to the send path)

When **`INSPECTIO_V3_PERSIST_EMIT_ENABLED=true`**, components emit **`PersistenceEventV1`** records to **persistence-transport SQS** (single queue or sharded queues). The **persistence writer** consumes those messages, batches events, writes **gzip NDJSON segments** to **S3** under a configured prefix, then **acks** (deletes) transport messages after a successful flush. **Checkpoint** objects advance only after **segment** data is on S3 (segment-before-checkpoint ordering).

**Event types** include at least:

- **`enqueued`** — emitted from L2 after a successful bulk enqueue (carries **`count`**, `batchCorrelationId`, etc.).
- **`attempt_result`** / **`terminal`** — emitted from workers around send attempts and terminal outcomes.

S3 therefore holds a **journal of lifecycle events**, not “one row per admitted HTTP call” unless you aggregate by type.

### 1.3 L2 “fast ack” persistence enqueue (throughput optimization)

To reduce admission latency, L2 can buffer **`enqueued`** emissions in an **in-process `asyncio` queue** and **flush** them to SQS in batches (`SendMessageBatch`, time/size triggers), with a **lifespan shutdown** flush. The HTTP response can return **after `put_nowait`** to that buffer — **before** the event is durably on **persistence-transport SQS** or S3.

**Review implication:** Process death between **HTTP 202** and **background flush** can produce **successful admission without a corresponding persistence event**, even when **`dropped_backpressure`** is zero (that metric applies after the producer queue, not to RAM before it).

### 1.4 Durability modes

- **`best_effort`:** Some persistence publish failures may be absorbed per policy (e.g. backpressure / DLQ paths) without failing HTTP admission.
- **`strict`:** Stricter coupling between publish success and caller behavior (used when you need failures to surface).

---

## 2. Why messages look “missing” (verification vs reality)

Observed example: Job **`inspectio-v3-sent-s3-verify`** admitted **10 000** messages, drained queues, waited for checkpoint stability, then compared against S3 and reported:

- **`terminal_success_unique=9065`** vs **10 000** admitted → **`VERIFY_FAIL`**, **`all_sent_persisted_match: false`**.

That is **not automatically a bug in S3 listing**; it is often **expected** under one or more of the following mechanisms:

### 2.1 Different definitions of “message” and “persisted”

- **Admitted** usually means **logical messages accepted** by the repeat/bulk API (`accepted` / `count` sum).
- **S3 verify scripts** often count **specific event types** (e.g. **terminal + success**) and **unique `messageId`s** seen in the journal.
- **Gap** means: “we have not yet observed a terminal-success persistence record for every admitted id,” which can include **not yet processed** units, **non-success** terminals, **dedupe** semantics, or **scan coverage** limits — not only “S3 lost data.”

### 2.2 Throughput asymmetry (admission ≫ worker completion)

If **admit RPS** is far higher than **worker + expander completion RPS**, **send queues backlog** grows. Messages are **still in SQS** (or invisible due to in-flight consumers) and may **never reach terminal** within a **fixed drain timeout**, or reach it **after** the verifier stops counting. That shows up as “missing” in **terminal-based** S3 checks even though **bulk admission** succeeded.

### 2.3 Persistence journal vs send completion

- **`enqueued`** events prove **admission was handed to the persistence transport** (subject to §1.3).
- **`terminal`** events prove the **worker path** reached a terminal outcome and emitted it.

A system can be **healthy** but **misaligned** for a test that assumes: *every admitted message must have a terminal-success row in S3 within T seconds*.

### 2.4 Fast-path buffer + restarts

API **rollouts**, **OOMKills**, or **liveness failures** during a burst can drop **unflushed** `enqueued` buffers, while clients already received **202**. That inflates gaps between **admitted** and **`enqueued`** lines in S3 (and anything downstream of them).

### 2.5 Metrics are per process and reset on restart

`GET /internal/persistence-transport-metrics` is **per uvicorn worker process** and **resets on pod restart**. Comparing **`published_ok`** on two API pods to **total admissions** without aligning **time windows** and **pod lifetime** can look like “missing publishes” when the real issue is **counter scope**.

---

## 3. Throughput with persistence enabled (confirmed numbers)

### 3.1 Admission-side (measured on EKS, persistence ON)

**In-cluster** Job using **`scripts/v3_sustained_admit.py`** against L1, with **`INSPECTIO_V3_PERSIST_EMIT_ENABLED=true`** in ConfigMap, reported:

| Metric | Value |
|--------|--------|
| **Duration** | 120 s |
| **Concurrency × batch** | 60 × 200 |
| **`admitted_total`** | 3 477 600 logical messages |
| **`offered_admit_rps`** | **~28 980** messages/s (driver-reported) |
| **Transient HTTP errors** | 0 |

**Interpretation:** This is **HTTP admission throughput** (repeat endpoint), not “SQS send-queue deletes per second” or “S3 terminal lines per second.” It **does** show that with persistence **enabled**, the **admission path** sustained **well above 10k messages/s** in that run.

### 3.2 Writer-side (order of magnitude)

Persistence writer snapshots under load showed **ingest** on the order of **hundreds of persistence events per second** per writer process (exact figure depends on shard count, event mix — `enqueued` vs `attempt`/`terminal` — and flush settings). That number is **not** directly comparable to **28k admit msg/s** because **one admission** can be **one `enqueued` event** carrying **`count`=200**, while workers add **many more events per message** over time.

### 3.3 What was *not* re-certified in this write-up

- End-to-end **“every admitted message has a terminal-success S3 record within T”** for the **28k msg/s** burst.
- **CloudWatch completion RPS** (e.g. **`NumberOfMessagesDeleted`** on send queues) for that specific sustain window.

Those require a **scoped test** (known N, strict or graceful drain, aligned verifier timeouts) and are **orthogonal** to the raw **admit RPS** figure above.

---

## 4. Review checklist (recommended)

1. **Clarify the durability contract** for the product: Is **HTTP 202** allowed to mean “bulk accepted to SQS” **without** a guaranteed **`enqueued`** persistence row yet? If not, **strict** mode and/or **await-after-flush** on the admission path is required.
2. **Align verification** with the contract: same **time horizon**, **event type**, and **id** field; distinguish **backlog** from **loss**.
3. **Capacity planning:** match **expander + worker** scale to **admit RPS** if terminal completeness in S3 within **T** is a gate.
4. **Operate:** after persistence or L2 changes, **full stack recycle** before benchmarking; for audits, **drain** persistence-transport queues and compare **S3 `enqueued` `sum(count)`** to **driver `admitted_total`** for a **small** controlled run.

---

*This document reflects architecture and measurements discussed around EKS deploy `inspectio-eks-20260407` and in-cluster Jobs (`inspectio-v3-sustain-perf`, `inspectio-v3-sent-s3-verify`). Adjust numbers if you re-run on a different topology or image tag.*
