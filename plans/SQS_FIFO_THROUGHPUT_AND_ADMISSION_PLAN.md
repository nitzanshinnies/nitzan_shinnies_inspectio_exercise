# SQS FIFO: throughput, admission, and NFR alignment

This document is the **normative design plan** for **SQS FIFO ingest** on the API admission path. It documents batch limits, **`MessageGroupId`** semantics, safe parallelism, backpressure, and how to validate aggregate throughput in-cluster.

**Related:** `plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md` (§1, §9 Phase 1, §10.3, §12, §15–§17, N1), `plans/IMPLEMENTATION_PHASES.md` (**P3** admission, **P5** consumer).

---

## 1. Problem statement

### 1.1 FIFO batch limits (AWS)

| Aspect | SQS FIFO `SendMessageBatch` |
|--------|------------------------------|
| Batch size | Up to **10** messages per call (hard limit) |
| Ordering | Per **`MessageGroupId`** FIFO ordering |
| Throughput | **Parallelize** `SendMessageBatch` **across** distinct **`MessageGroupId`** values; **serialize** per group when strict ordering is required |

The implementation uses `MAX_SQS_FIFO_SEND_BATCH = 10` in `src/inspectio/ingest/sqs_fifo_producer.py` and chunks accordingly.

### 1.2 Observed admission bottleneck

`SqsFifoIngestProducer.put_messages` may send chunks **sequentially** in a `for` loop: each chunk awaits `_send_fifo_batch` → `send_message_batch`. That is **correct async I/O** (non-blocking) but **not parallel**: wall-clock time scales with **number of sequential batches × latency per batch**.

**Critical distinction (repeat vs single-shard):**

- **`POST /messages/repeat`** creates **N independent `messageId`s** (blueprint **§15.2**). **`shardId`** is **`SHA256(messageId) % TOTAL_SHARDS`** (**§16.2**). For default **`TOTAL_SHARDS = 1024`**, a large repeat spreads admits across **many** distinct shards, hence **many** distinct **`MessageGroupId`** values. So a **single** repeat request is **multi-group** unless implementation collapses groups (it should not).
- **`POST /messages`** with one message, or synthetic tests that force one shard, behave as **single-group** admits.

So the main production gap is: **serial batch loop over a list that is already multi-group** — that **artificially serializes** work that FIFO semantics allow to run **concurrently across groups**. Fixing that (§4.2, **SQS-P1**) is the primary lever for **§9 Phase 1** acceptance (“no 60s submit timeout at **10k** batch profile”) and for **aggregate** N1.

---

## 2. AWS FIFO semantics and limits (design constraints)

These bound any admission strategy. **Authoritative detail:** [Amazon SQS quotas](https://docs.aws.amazon.com/general/latest/gr/sqs-service.html), [FIFO message quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html), [High throughput for FIFO queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/high-throughput-fifo.html).

1. **`SendMessageBatch`:** at most **10** entries per call for FIFO queues.
2. **Ordering:** FIFO order is **per `MessageGroupId`**, not global.
3. **Parallel sends:** **Concurrent** `SendMessageBatch` / `SendMessage` calls targeting the **same** `MessageGroupId` are **unsafe** if the product requires **strict ordering** of admits for that group (overlapping in-flight batches can violate per-group ordering expectations). **Concurrent** sends targeting **different** `MessageGroupId`s are **required** for throughput when the API has work for many groups in one `put_messages` invocation.
4. **Throughput (qualitative):** High-throughput FIFO uses **partitions**; AWS scales partitions when request rate approaches limits. **Per partition**, documentation references **up to ~3,000 messages per second with batching** in supported regions (see high-throughput FIFO page above). **Regional and account quotas** still apply; expect **`Throttling`** under abuse and design **backoff** + **bounded concurrency**.

**Project mapping:** `MessageGroupId` comes from **`partition_key_for_shard(shard_id)`** (same routing idea as ingest). **One shard id** ⇒ **one** group for those rows. **Repeat** ⇒ many shard ids ⇒ **many** groups in one HTTP request.

---

## 3. Blueprint and NFR reconciliation

This section **locks** how **`plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** requirements map to **SQS FIFO**.

| Blueprint reference | Requirement | SQS FIFO interpretation |
|---------------------|-------------|-------------------------|
| **G1 / N1** | Design for **tens of thousands/sec** | **Aggregate** sustained **submit** rate across **many** message groups (shards) and **scaled** API + worker replicas. Not a promise that **one** `MessageGroupId` sustains 10k+ msg/s. |
| **§1** | High ingest throughput **`POST /messages/repeat`** without **60s** timeout failures | For **large `count`**, admits are **multi-group** (§1.2). **Must** use **parallel admission across groups** (§4.2) and size **ingress timeouts** above worst-case single-request latency. |
| **§9 Phase 1 — Acceptance** | **No 60s submit timeout** at **10k batch profile**; **p95** submit latency materially reduced vs baseline | **Engineering gate:** in-cluster **10k repeat** completes without client **disconnect** at configured timeout; **SQS-P1** (or equivalent) is **in scope** for this acceptance line, not optional polish. |
| **§12 DoD** | Submit path handles **large repeat batches** without **request-time disconnect** pattern | Same as above: **admission parallelism across groups** + **client/LB timeout** ≥ documented budget + **throttle backoff** that does not stall forever. |
| **§10.3** | Measure **submit throughput** (separately from scheduler, etc.); in-cluster for AWS | **Pass/fail** metrics belong in a **runbook** (§8); see **§7**. |
| **§15.2** | Large repeat with batched **`SendMessageBatch`** | **FIFO** remains **10** per call; compensate with **parallel batches across groups** + **worker drain** scaling. |

**Explicit:** A **single** serial loop over **all** batches for a **multi-shard** repeat is **not** sufficient for **§9 Phase 1** acceptance at **10k** scale; **SQS-P1** (or equivalent) is the **functional** fix (wider pipeline across groups).

---

## 4. Capacity model (order-of-magnitude)

Use this for **design reviews** and **SLO budgets**. Replace constants with **measured** `T_batch` from perf logs or in-cluster traces.

### 4.1 Per `MessageGroupId` (serialized batches)

Let **`T_batch`** = wall-clock time for one successful `SendMessageBatch` (network + AWS), **~20–80 ms** typical (region, TLS, size; measure).

- **Messages per second for one group** (upper bound, no throttling):

  \[
  R_{\text{group}} \approx \frac{10}{T_{\text{batch}}}
  \]

  Example: **`T_batch = 40 ms`** ⇒ **\(R_{\text{group}} \approx 250\)** msg/s for that shard.

- **Time to admit `N` messages** for **one** group (all sequential):

  \[
  T_{\text{1-group}} \approx \left\lceil \frac{N}{10} \right\rceil \times T_{\text{batch}}
  \]

  Example: **`N = 10\,000`**, **`T_batch = 40 ms`** ⇒ **1,000 × 0.04 s ≈ 40 s** **SQS send time alone** before response build — **high risk** of **60s** client/LB timeouts if **everything** were one group.

### 4.2 `POST /messages/repeat` (multi-group)

Let **`S`** = number of **distinct** `shardId` values in the request (**1 ≤ S ≤ min(N, TOTAL_SHARDS)**). With **uniform** `messageId` hashing (**§16.2**), large **`N`** typically yields **many** distinct shards (**S** approaches **`min(N, TOTAL_SHARDS)`** in expectation).

Let **`P`** = **admission parallelism** = maximum concurrent `SendMessageBatch` calls **across different groups** (bounded by **settings**, HTTP client, and process).

**Rough** wall-clock lower bound for **SQS sends only** (ignoring JSON build and fan-in), if batches are balanced across groups:

\[
T_{\text{multi-group}} \gtrsim \left\lceil \frac{\lceil N/10 \rceil}{P_{\text{eff}}} \right\rceil \times T_{\text{batch}}
\]

where **`P_eff = min(P, S, …)`** (cannot exceed distinct groups or sensible AWS limits).

**Example (illustrative):** **`N = 10\,000`**, **`S ≈ 1024`**, **`~10` messages per shard on average**, **one batch per shard** ⇒ **~1,000** batches total. If **`P = 64`**, **`T_batch = 40 ms`** ⇒ **⌈1000/64⌉ × 0.04 ≈ 0.64 s** for SQS **admit** phase (plus HTTP overhead) — **consistent** with **§9** “no 60s timeout” **if** **`P` is not 1**.

**Conclusion:** **Serial `P = 1`** over multi-group repeat is a **defect** relative to blueprint acceptance; **SQS-P1** is **required**, not optional.

### 4.3 Aggregate **N1** (“tens of thousands/sec”)

**System** submit rate is roughly:

\[
R_{\text{submit}} \approx \sum_{\text{groups } g} R_g
\]

with **`R_g`** capped per group as in §4.1 and **AWS** partition / quota limits. **Tens of thousands/sec** requires **enough** distinct hot groups **and/or** **multiple** API replicas **and** **queue + worker** capacity so **SQS depth** stays bounded.

**Worker drain:** If **`R_ingest` (API)** ≫ **`R_drain` (worker + journal + delete)**, latency grows without bound — scale **P5** (receive concurrency, replicas, flush) with **P3** admits.

---

## 5. Goals and non-goals

### 5.1 Goals

1. **Correctness first:** **§17 / §18** — dedupe (`MessageDeduplicationId`), per-shard ordering as consumed by the worker, **no** parallel **same-group** sends unless explicitly approved.
2. **Admission efficiency:** **Parallelize across `MessageGroupId`s** (§4.2); bounded concurrency; **reuse** HTTP client/session where possible.
3. **Measurable N1 and Phase 1 acceptance:** **§7** pass/fail gates, **in-cluster** for AWS throughput claims.

### 5.2 Non-goals (unless blueprint changes)

1. Replacing FIFO with **standard SQS** for raw TPS at the cost of ordering (conflicts with ingest semantics unless spec changes).
2. Claiming **N1** from **one** saturated **`MessageGroupId`** alone.
3. **Laptop port-forward** baselines for **AWS performance claims** (workspace rules).

---

## 6. Admission-path strategies

All strategies assume **idempotent** `SendMessageBatch` and existing **partial failure** handling (failed entries → single-message send).

### 6.1 Baseline (pre–SQS-P1)

- Chunks of ≤10; **strictly sequential** `await` for every batch.
- **Safe** for one group; **incorrect performance posture** for **multi-group** `put_messages` (repeat).

### 6.2 Bounded parallelism **across** `MessageGroupId`s (**required** for repeat)

1. **Partition** inputs by **`partition_key_for_shard(shard_id)`** (or shard id).
2. **Per group:** serialized pipeline of batches (≤10 messages each) — preserves **per-group** order.
3. **Across groups:** bounded **`asyncio`** concurrency (semaphore), **`max_inflight_groups`** / global cap in **Settings**.

**Pros:** Unlocks **§9 Phase 1** and **§12** for **10k**-scale repeat **without** relying on external clients to shard requests.  
**Cons:** Still **does not** raise **single-group** `R_group` beyond §4.1 (physics + AWS).

### 6.3 Same-group mega-admit

| Option | Behavior | When |
|--------|----------|------|
| **A. Serialized batches** | Default; strict ordering | Single-shard workloads, or last-mile batches inside one group |
| **B. Relaxed ordering** | Only if blueprint + tests explicitly allow | Rare; journal SoT usually forbids |
| **C. Client workload split** | Multiple requests or smaller **`count`** | **Supplemental**; **not** a substitute for **6.2** for standard repeat |

**Recommendation:** **6.2** + **6.3-A**; document **§4.1** for ops when **`S = 1`**.

### 6.4 Backpressure and errors

1. **Retry:** exponential backoff on throttling; cap; map to **503** / **429** per **§15** when ingest unavailable.
2. **Bounded memory:** cap concurrent in-flight **batches**; never unbounded **`gather`** without limits.
3. **Partial batch failure:** keep “failed entry → single send”; track **retry fraction** (perf logs / metrics).

---

## 7. Consumer and worker side

Throughput is **not** admission-only. **P5** (`SqsFifoBatchFetcher`, `IngestConsumer`, journal flush) must match **admit** rate in steady state.

- Size **receive** concurrency, **long polling**, **DeleteMessage** after **§18.3**, and **worker replicas** so **ApproximateAgeOfOldestMessage** does not grow without bound under target load.
- Any **SQS-P1** rollout must include a **paired** check: **queue depth** + **worker CPU** + **journal** flush latency.

---

## 8. Validation, metrics, and pass/fail gates

### 8.1 Honest measurement (always)

1. **Single-group microbenchmark:** **p95** vs **`N`** for **`S = 1`** — validates **§4.1** (latency, not aggregate TPS).
2. **Repeat / multi-group:** **p95** submit time for **`count ∈ {1k, 2k, 5k, 8k, 10k}`** in-cluster — validates **§9 Phase 1** and **TC-PERF-002** intent.
3. **Aggregate N1:** many clients, sustained **admit rate** + **SQS depth** + **end-to-end** lag — validates **G1/N1** as **system** design.

**Driver:** `scripts/full_flow_load_test.py` **in-cluster** per repo rules; **full stack recycle** before runs.

### 8.2 Pass/fail (architectural gates)

| Gate | Criterion | Blueprint trace |
|------|-----------|-----------------|
| **G-PHASE1-SUBMIT** | **10k** repeat completes **without** client **disconnect** at **documented** timeout (ingress + client); **no** systematic **~60s** failure mode | **§9 Phase 1**, **§1**, **§12** |
| **G-SQS-P1** | Multi-group admit uses **parallel batches across groups** (code + tests); **no** unbounded same-group parallelism | **§17**, this doc §6.2 |
| **G-N1-SYSTEM** | Sustained **submit** throughput in the **tens of thousands/sec** **order of magnitude** under declared **concurrency + shard** mix, with **stable** queue depth | **N1**, **§10.3** |
| **G-DRAIN** | Workers + journal **drain** admitted volume without **unbounded** backlog under same test | **§10.3**, **P5** |

**TC-PERF-002** (blueprint **§28**): **10k** in-cluster — **document** latency from Job logs only; **G-PHASE1-SUBMIT** must be **green** before claiming **Phase 1** complete.

Record commands, env, and results in **§26** runbook / perf appendix — not only PR text.

---

## 9. Suggested implementation phases (follow-up PRs)

| Phase | Content | Exit criteria |
|-------|---------|----------------|
| **SQS-P1** | Partition-by-group + bounded concurrent pipelines in `SqsFifoIngestProducer`; **`max_inflight_groups`** (and global cap) in **Settings** | Unit tests: multi-group ⇒ concurrent `SendMessageBatch`; single-group ⇒ **no** overlap; optional perf smoke **count=1k** faster than serial baseline |
| **SQS-P2** | Throttle-aware backoff; throttle metrics | Integration or LocalStack fault injection where feasible |
| **SQS-P3** | In-cluster **2k–10k** matrix; **G-PHASE1-SUBMIT** + **G-N1-SYSTEM** evidence in runbook | Tables + logs archived; **IMPLEMENTATION_PHASES** / README pointer |

---

## 10. Checklist before merging admission changes

- [ ] **§16.2** shard distribution understood for **repeat** (multi-group).
- [ ] **No** overlapping in-flight batches for the **same** `MessageGroupId` unless **explicitly** approved.
- [ ] **G-PHASE1-SUBMIT** / **G-SQS-P1** satisfied or **explicit** waiver documented.
- [ ] Load methodology: **in-cluster** for AWS claims; stack **recycled** before load.
- [ ] **`IMPLEMENTATION_PHASES.md` P3** row matches: chunk ≤10, `MessageGroupId` = shard partition.

---

## 11. Revision history

| Date | Change |
|------|--------|
| 2025-03-26 | Initial plan: FIFO limits, sequential vs cross-group parallelism, NFR validation, phased rollout |
| 2026-03-26 | Architect pass: **§16.2** repeat **multi-group** correction; **§3** blueprint reconciliation; **§4** capacity model; **§8** pass/fail gates; **§9** SQS-P1 as **Phase 1** requirement |
| 2026-03-26 | **SQS-only** doc: removed legacy stream comparisons; **§17** is normative |
