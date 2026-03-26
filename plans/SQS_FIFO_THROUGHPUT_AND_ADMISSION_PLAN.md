# SQS FIFO: throughput, admission, and NFR alignment

This document is the **normative design plan** for improving and correctly measuring **SQS FIFO ingest** on the API admission path, after the **Kinesis → SQS FIFO** migration driven by account/SCP constraints. It exists so future work does not assume **Kinesis `PutRecords`** batch sizes or semantics.

**Related:** `plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md` (§17 ingest), `plans/IMPLEMENTATION_PHASES.md` (**P3** admission, **P5** consumer).

---

## 1. Problem statement

### 1.1 What changed vs Kinesis

| Aspect | Kinesis `PutRecords` (prior mental model) | SQS FIFO `SendMessageBatch` (current) |
|--------|-------------------------------------------|----------------------------------------|
| Batch size | Up to **500** records per call | Up to **10** messages per call (hard limit) |
| Ordering | Per-shard stream sequence | Per **`MessageGroupId`** FIFO ordering |
| Throughput story | Fewer round-trips per volume | **More round-trips** for the same message count |

The implementation uses `MAX_SQS_FIFO_SEND_BATCH = 10` in `src/inspectio/ingest/sqs_fifo_producer.py` and chunks accordingly.

### 1.2 Observed admission bottleneck

`SqsFifoIngestProducer.put_messages` sends chunks **sequentially** in a `for` loop: each chunk awaits `_send_fifo_batch` → `send_message_batch`. That is **correct async I/O** (non-blocking) but **not parallel**: wall-clock time for a large admit scales roughly with **number of chunks × latency per batch**, dominated by sequential awaits.

So a single request that admits **tens of thousands** of messages to **one** FIFO group pays **many sequential** SQS round-trips. That is a **latency** and **per-request throughput** issue, not something “async” alone fixes.

---

## 2. AWS FIFO semantics and limits (design constraints)

These are **not** implementation details; they bound any admission strategy.

1. **`SendMessageBatch`**: at most **10** entries per call for FIFO queues.
2. **Ordering**: strict **FIFO order is per `MessageGroupId`**, not globally across the queue.
3. **Implication for parallel sends**: issuing **multiple concurrent** `SendMessageBatch` (or `SendMessage`) calls that target the **same** `MessageGroupId` can **reorder** relative to send completion order unless a single serialized pipeline is used. The service orders by **successful acceptance** semantics per group; overlapping in-flight batches for one group are unsafe if the product requires **strict ordering of admits** for that group.
4. **Throughput**: FIFO queues have **per-queue** and **per-message-group** throughput characteristics (AWS documents “high throughput FIFO” and quotas). Design must assume **throttling** (`Throttling`, HTTP 429-class behavior) under load and define **backoff** and **bounded concurrency**.

**Project mapping:** `MessageGroupId` is derived from the shard via `partition_key_for_shard` in `sqs_fifo_producer.py` (same idea as ingest routing). A **single-shard** workload maps to **one** group for those messages.

---

## 3. Goals and non-goals

### 3.1 Goals

1. **Correctness first:** preserve **§17 / journal** expectations: ingest records must remain **deduplicated** (`MessageDeduplicationId` from idempotency key) and **consumable in a defined order** per shard as required by the blueprint.
2. **Admission efficiency:** maximize **safe** parallelism where FIFO semantics allow it; minimize unnecessary work on the hot path (client reuse, batching, avoid redundant retries).
3. **Honest NFR validation:** separate **single-request mega-admit** behavior from **aggregate** system throughput under **many concurrent clients** and **many shards/groups** (see §6).

### 3.2 Non-goals (unless blueprint explicitly changes)

1. Switching to **standard SQS** to get higher throughput by **sacrificing FIFO ordering** (likely violates ingest ordering assumptions).
2. Claiming “tens of thousands/sec” from **one** `/messages/repeat` to **one** shard without stating that FIFO **per-group** semantics force **serialized** admits for that group.
3. Using **laptop `port-forward`** for AWS/EKS performance baselines (see repo rules: **in-cluster** load tests for real AWS claims).

---

## 4. Admission-path strategies

All strategies assume **idempotent** `SendMessageBatch` behavior and existing **partial failure** handling (retry failed entries via single-message send in current code).

### 4.1 Baseline (current)

- Chunk messages into groups of ≤10; **await each batch** in order.
- **Pros:** Simple; **safe** for a **single `MessageGroupId`** stream (one shard per request pattern).
- **Cons:** For **N** messages and one group, **⌈N/10⌉** sequential round-trips.

### 4.2 Bounded parallelism **across** `MessageGroupId`s

When `put_messages` receives inputs for **multiple shards** (hence **multiple** `MessageGroupId`s), batches that touch **disjoint** groups do not need to serialize with each other for **ordering between groups** (ordering is only defined **within** a group).

**Design:**

1. **Partition** the input list by `partition_key_for_shard(shard_id)` (or raw shard id).
2. For each group, run a **serialized** pipeline of batches (≤10) for that group.
3. Across groups, run pipelines with a **bounded** concurrency limit (semaphore or worker pool), e.g. `max_inflight_groups`, configurable via settings.

**Pros:** Improves wall-clock when a **single** API call fans out to **many** shards.  
**Cons:** Does not speed up the **single-group** mega-admit case.

### 4.3 Same-group mega-admit: options (must pick explicitly)

| Option | Behavior | When to use |
|--------|----------|-------------|
| **A. Keep strict sequential batches** | No parallelism within group; best for strict ordering | Default unless product accepts relaxed ordering |
| **B. Pipeline with documented relaxation** | If the blueprint allows **non-strict** ordering for bulk repeat (unlikely for journal SoT) | Only with blueprint + test updates |
| **C. Split workload** | Clients send **multiple smaller** admits or **multiple shards** | Operational / client pattern; validates aggregate TPS |

**Recommendation:** Implement **4.2** for multi-group admits; keep **4.3-A** for single-group unless requirements change.

### 4.4 Backpressure and errors

1. **Retry policy:** exponential backoff on throttling for `send_message_batch` and single-message fallback; cap retries; surface **503** or **429** to clients per API policy when ingest is unavailable.
2. **Bounded memory:** admission already chunks at route level (`MAX_PUT_RECORDS_BATCH = 500` in `routes_public.py`); producer should not buffer unbounded futures—respect **max concurrent in-flight batches** globally and per group.
3. **Partial batch failure:** preserve current “failed entries → single send” behavior; add metrics/perf lines for **retry fraction** (already partially instrumented on `perf/runtime-logging-from-eks`).

---

## 5. Consumer and worker side (short)

Throughput is **not** only API admission. **P5** (`SqsFifoBatchFetcher`, `IngestConsumer`, journal flush) determines end-to-end behavior.

- **Receive** concurrency, long polling, and **delete-after-journal** must be sized so the queue does not grow without bound under load.
- Any admission optimization should be validated **together** with worker scaling (replicas, batch receive sizes, journal flush policy).

This plan focuses on **admission**, but **P10 / in-cluster load** must cover the **full path**.

---

## 6. How to validate throughput honestly (NFR)

1. **Single request, one shard:** measure **p95 API time** vs message count; expect **linear-ish** steps with **⌈N/10⌉** batches unless implementation changes **within-group** strategy. Use this to validate **latency**, not “system max TPS.”
2. **Aggregate throughput:** many **concurrent** clients (load harness), **many shards** / groups, sustained steady state; measure **admitted/sec** at API and **lag** at SQS + journal.
3. **AWS/EKS:** run **`scripts/full_flow_load_test.py` in-cluster** per project rules; restart/recycle stack before runs as documented.

Document results in the performance section of the blueprint or a dedicated **runbook**, not only in PR descriptions.

---

## 7. Suggested implementation phases (follow-up PRs)

| Phase | Content | Exit criteria |
|-------|---------|----------------|
| **SQS-P1** | Partition-by-group + bounded concurrent group pipelines in `SqsFifoIngestProducer`; settings for `max_inflight_groups` (and optional global cap) | Unit tests with mocked SQS: multi-group admits issue concurrent batches; single-group remains ordered |
| **SQS-P2** | Throttle-aware retry/backoff; structured logging for throttle rate | Integration test or fault injection against LocalStack where supported |
| **SQS-P3** | In-cluster load + before/after numbers documented; update **P3** notes in `IMPLEMENTATION_PHASES.md` if exit criteria change | In-cluster run artifacts / summary |

---

## 8. Checklist before merging admission changes

- [ ] Blueprint/journal ordering assumptions re-read (**§17–18**).
- [ ] No parallel in-flight **same** `MessageGroupId` batches unless explicitly approved.
- [ ] Load methodology matches repo rules (in-cluster for AWS claims).
- [ ] `IMPLEMENTATION_PHASES.md` **P3** row still matches behavior (chunk ≤10, `MessageGroupId` = shard partition).

---

## 9. Revision history

| Date | Change |
|------|--------|
| 2025-03-26 | Initial plan: FIFO limits, sequential vs cross-group parallelism, NFR validation, phased rollout |
