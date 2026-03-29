# V3 — validation checklist (master plan ↔ phases)

**Normative doc:** `plans/V3_ASYNC_PIPELINE_IMPLEMENTATION_PLAN.md`. **Phase specs:** this folder (`P0`–`P7`).

**How to use:** Tick **`[ ]` → `[x]`** when the **implementation** and **tests** satisfy the row. **`Phase`** is where to look first in the phase markdown; some rows span multiple PRs.

---

## A) Traceability themes (master section 0, ASSIGNMENT.pdf)

| # | Requirement (summary) | Phase | Verified |
|---|------------------------|-------|----------|
| A1 | Arrival → `SendUnitV1` + worker **newMessage**-equivalent; bulk → one **BulkIntentV1** → **N** units | P3, P4 | [ ] |
| A2 | **wakeup** ~**500 ms**, concurrent with receive; no receive starvation | P4 | [ ] |
| A3 | **boolean send** → internal **`try_send`**, scheduler uses **`bool`** | P0, P4 | [ ] |
| A4 | Retry **#1–#6** absolute from **`receivedAtMs`**; **6** fails → **failed** | P0, P4 | [ ] |
| A5 | REST **4.1** + **`openapi.yaml`** | P1 | [ ] |
| A6 | **Repeat** response: ids **or** summary (document in OpenAPI) | P1 | [ ] |
| A7 | Outcomes last **100**, fields + sort (**4.8** / OpenAPI) | P4 | [ ] |
| A8 | Throughput design **tens of thousands/sec**; measure **3.1** in P7 | P2–P4, P7 | [ ] |
| A9 | Sharded queues + per-**messageId** lock only | P3, P4 | [ ] |
| A10 | L2 idempotency + expander dedupe (**4.2**) | P1, P3 | [ ] |
| A11 | **AC5** / S3 restart — **deferred**; documented in README | P4+ | [ ] |
| A12 | NFR **time**: not before **nextDueAt**; not wildly late under load | P4 | [ ] |
| A13 | README: structures, sync, complexity, gaps, AWS, **future S3 schema** | P4+ | [ ] |
| A14 | Runs on **AWS** (EKS/ECS/EC2) + credentials — **AC6** | P6, P7 | [ ] |

---

## B) Architecture layers (master section 2)

| # | Layer | Phase | Verified |
|---|--------|-------|----------|
| B1 | **L1** static + proxy; browser → L1 only; one **repeat** POST | P5 | [ ] |
| B2 | **L2** stateless admission, **BulkIntentV1** → SQS, no **`send()`** here | P1, P2 | [ ] |
| B3 | **L3** expander: **BulkIntentV1** → **N × SendUnitV1**, standard + **K** shards | P3 | [ ] |
| B4 | **L4** worker: scheduler + **`try_send`** + terminals → **OutcomesStore** | P4 | [ ] |
| B5 | **L5** optional persist queue stub (**4.3**); no S3 journal in phase 1 | P2, P4 | [ ] |

---

## C) Contracts & performance (master sections 3–4, 8)

| # | Topic | Phase | Verified |
|---|--------|-------|----------|
| C1 | Admission **O(1) in N**; repeat = one bulk enqueue (**3.2**) | P1 | [ ] |
| C2 | SQS **receive → handle → delete** scalable (**batch receive**, replicas) (**3.2**, **7.2**) | P3, P4 | [ ] |
| C3 | Primary metric **3.1** (`try_send` / send path after dequeue); **p50/p99** | P7 | [ ] |
| C4 | Queue topology **4.3** (`BULK`, send shard URLs, optional persist) | P2, P3 | [ ] |
| C5 | **`stable_hash(messageId) % K`** | P3 | [ ] |
| C6 | Envelopes **4.4** (**schemaVersion**, **traceId**, **batchCorrelationId**, **attemptsCompleted**) | P0 | [ ] |
| C7 | Outcomes shared store; **not** L2-only memory with **replicas > 1** (**4.8**) | P4 | [ ] |
| C8 | Observability **8** (logs: trace/batch/message/shard; counters: expanded, send_ok/fail, sqs_throttle) | P3, P4 | [ ] |

---

## D) Agent rules & gates (master section 6)

| # | Rule (summary) | Phase | Verified |
|---|----------------|-------|----------|
| D1 | Tests + markers; new behavior → tests | P0–P7 | [ ] |
| D2 | OpenAPI-first HTTP | P1 | [ ] |
| D3 | **SQS** required; **no Kinesis**; SNS/Lambda/DynamoDB only if approved (**9**) | P2–P4, P6 | [ ] |
| D4 | AWS perf claims → in-cluster Job only | P7 | [ ] |
| D5 | Bounded Job / **`kubectl wait`** | P7 | [ ] |
| D6 | README PDF deliverables + gaps | P4+ | [ ] |
| D7 | No legacy **`v2_obsolete/archive`** imports in **src** / **tests** | P0–P7 | [ ] |

---

## E) V3 pipeline acceptance (master section 7.2)

| # | Checklist item | Phase | Verified |
|---|----------------|-------|----------|
| E1 | L1 → L2 proxy for browser clients | P5 | [ ] |
| E2 | **Repeat** = one HTTP request; expander creates **N** units | P1, P3 | [ ] |
| E3 | Sharded send queues + **batch** publish/consume | P3, P4 | [ ] |
| E4 | Outcomes consistent across L2 replicas | P4, P6 | [ ] |
| E5 | Load script reports **send RPS**; AWS from in-cluster only | P7 | [ ] |

---

## F) PDF AC quick map (master section 7.1)

| AC | Phase (primary) | Verified |
|----|-----------------|----------|
| AC1 | P4 | [ ] |
| AC2 | P4 | [ ] |
| AC3 | P4 | [ ] |
| AC4 | P4 | [ ] |
| AC5 | Document only (deferred) | [ ] |
| AC6 | P6, P7 | [ ] |

---

**Index:** [README.md](./README.md) · phase files **P0**–**P7**
