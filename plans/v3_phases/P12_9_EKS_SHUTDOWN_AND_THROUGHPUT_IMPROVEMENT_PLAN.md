# P12.9 — EKS cost shutdown + throughput improvement plan

## 1. EKS shutdown (compute)

**Executed (2026-04-02):** `eksctl scale nodegroup --cluster nitzan-inspectio --region us-east-1 --name ng-main --nodes 0 --nodes-min 0`

**Resulting nodegroup state:** `MIN SIZE = 0`, `DESIRED CAPACITY = 0`, `STATUS = ACTIVE`.

**Stale check:** Capacity may have been scaled **up** again for later benchmark runs. Treat this section as **what the shutdown command does**; for **current** billing/state, use `eksctl get nodegroup …` and/or **`P12_9_SESSION_RECOVERY_PLAN.md`** (frozen handoff / cost pause).

Worker nodes enter **drain** (`SchedulingDisabled`) and then **terminate**; **EC2 instance charges for the nodegroup stop** once instances are gone.

### What still may bill (not stopped by this command)

| Item | Note |
|------|------|
| **EKS control plane** | Hourly per cluster unless the cluster is deleted. |
| **EBS / snapshots** | If any PVCs or volumes remain (often minimal if stateless). |
| **NAT Gateway, ALB/NLB, public IPs** | If present in the VPC for this exercise. |
| **ECR storage** | Images pushed to `194768394273.dkr.ecr...`. |
| **S3, SQS, CloudWatch** | Usage-based; not “cluster idle” but not node compute. |

**Bring workloads back:** restore capacity, e.g. `eksctl scale nodegroup --cluster nitzan-inspectio --region us-east-1 --name ng-main --nodes 12 --nodes-min 2` (adjust to prior sizing), wait for nodes `Ready`, then confirm rollouts. Follow `P12_9_ITER6_TEST_EXECUTION_SPEC.md` / `P12_9_AI_SE_PLAN_D_EKS_BENCHMARK_EXECUTION.md` for full-stack recycle before benchmarks.

---

## 2. Current v3 architecture (reference diagram)

**Scope:** In-cluster load test path and persistence backup path, **K=8** send shards and matching persistence transport/writer shards as deployed on EKS.

```mermaid
flowchart LR
  subgraph drivers["Benchmark / clients"]
    JOB["Kubernetes Job\n(v3_sustained_admit)"]
  end

  subgraph edge["Edge"]
    L1["L1\n(reverse proxy + static UI)"]
  end

  subgraph l2["L2 API"]
    API["FastAPI L2\n(/messages/repeat, …)"]
    REDIS[("Redis\nscheduler / runtime state")]
  end

  subgraph sqs_bulk["SQS — bulk path"]
    QBULK[["Bulk intent queue\n(L2 → expander)"]]
  end

  subgraph expander_tier["Expander service"]
    EXP["Expander\nfan-out / dedupe / shard routing"]
  end

  subgraph sqs_send["SQS — send shards (×K)"]
    Q0[["inspectio-v3-send-0"]]
    QK[["… send-(K-1)"]]
  end

  subgraph workers["Worker tier (per shard)"]
    W0["Worker shard 0…"]
    WK["Worker shard K-1…"]
  end

  subgraph persist_opt["Persistence (when emit enabled)"]
    QPT[["Persistence transport\nSQS (per shard)"]]
    PWR["Persistence writer\n(per shard)"]
    S3[("S3\nsegments / checkpoints")]
  end

  JOB -->|HTTP POST| L1
  L1 -->|proxy| API
  API <--> REDIS
  API -->|enqueue bulk| QBULK
  QBULK --> EXP
  EXP --> Q0
  EXP --> QK
  Q0 --> W0
  QK --> WK
  W0 -.->|optional emit| QPT
  WK -.->|optional emit| QPT
  QPT --> PWR
  PWR --> S3
  PWR -->|delete / ack\n(transport)| QPT
  W0 -->|delete\n(send complete)| Q0
  WK -->|delete\n(send complete)| QK
```

**Reading the diagram**

- **Completion RPS (hygiene)** ≈ sum of **`NumberOfMessagesDeleted`** on **`inspectio-v3-send-*`** — i.e. **send-queue message throughput** after workers finish a unit of work and **delete** the SQS message.
- **Scheduler SoT** for live sending is **in-memory + Redis + SQS visibility**, not S3 (`P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md`).
- **Persist-on:** workers **emit** events to **persistence transport** queues; **writers** flush to **S3** then **ack/delete** transport messages. If that path is slow, **on-leg completion** (send deletes) can lag even when **persist-off** is healthy.

---

## 3. Improvement plan (ordered)

Goals: raise **sustained completion RPS** (especially **persist-on / off ratio** vs gates), without violating **memory + SQS** scheduling intent.

### Phase A — Measure and target the bottleneck (no guessing)

1. For the next EKS run, capture **per-tier** signals already partially available: driver **`offered_admit_rps`**, hygiene **`combined_avg_rps`**, **ApproximateNumberOfMessagesVisible** on bulk + send queues during the window, **CPU** on L2/expander/worker/writer pods (metrics-server or CloudWatch Container Insights if enabled).
2. **Interpret gaps:**
   - Admits ≫ SQS send deletes → **L2 → bulk → expander → enqueue** path.
   - Deep send queues + hot workers → **worker throughput** or **per-queue SQS consumer contention**.
   - Shallow queues, low CPU, low deletes → **under-offered load** or **front-end limit** (L1/L2 concurrency).

### Phase B — Software tuning (cheap, gate-aligned)

Execute **`P12_9_AI_SE_PLAN_A_TRANSPORT_WRITER_TUNING.md`** and the writer knobs in **`P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md`** (ack concurrency, flush batch/interval, receive parallelism, emitter **`max_inflight`**, etc.). Re-benchmark with **Plan D** hygiene.

If Phase A shows **persist-off** capped by expander/L2, apply existing **expander / SqsBulkEnqueue** settings (`expander_publish_concurrency`, receive caps) before buying hardware.

### Phase C — Horizontal scale (where Phase A points)

| If saturated tier | Lever |
|-------------------|--------|
| L2 / API | Replicas, instance size, **httpx** / FastAPI limits, Redis latency |
| Expander | Replicas, publish/receive concurrency settings |
| Workers | **Replicas per send shard** (more consumers on same queue until diminishing returns) |
| Aggregate SQS envelope | **More send shards (K↑)** + routing + matching Deployments (structural scale-out) |
| Persistence path | Writer replicas are **per shard** in current model; tune **I/O and ack pipeline** first, then **shard count** for transport |

Avoid scaling a tier that is **not** backed up (queues shallow, CPU low).

### Phase D — Contract / durability (only if tuning + scale plateau)

If gates still fail after B+C, follow **`P12_9_AI_SE_PLAN_B_ASYNC_BACKUP_ACK_CONTRACT.md`** (explicit ack semantics vs `best_effort`) with signed-off failure modes — **not** a first resort.

### Phase E — Observability and hygiene

**`P12_9_AI_SE_PLAN_C_OBSERVABILITY.md`**: distinguish **send completion**, **backup lag**, **transport depth**, so regressions are visible in one run.

---

## 4. Links

| Doc | Use |
|-----|-----|
| `P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md` | Architecture intent (S3 = backup) |
| `P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md` | SE fix phases and gates |
| `P12_9_AI_SE_PLAN_A` … **D** | Tuning, ack contract, metrics, EKS execution |
| `P12_9_ITER6_TEST_EXECUTION_SPEC.md` | Benchmark protocol, optional rollback image |

---

## 5. Diagram maintenance

When **K**, service names, or the bulk-queue shape change, update **§2** and re-verify edges against `src/inspectio/v3/l1`, `…/expander`, `…/worker`, `…/persistence_writer`, and deploy manifests under `deploy/kubernetes/`.
