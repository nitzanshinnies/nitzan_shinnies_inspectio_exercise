# Architect plan — Inspectio v3 persistence, throughput, and AWS platform

**Audience:** Software / systems architects and tech leads owning Inspectio v3.  
**Intent:** One readable spine that connects **measured bottlenecks**, **execution plans already in-repo**, **AWS/org constraints**, and **decision gates**. It does not replace detailed specs; it points to them.

**How to use:** Read §1–3 for context, §4 for priorities, §5 for phased roadmap and exit criteria, §6 for decisions that need explicit sign-off, **§9 for live execution status and the next concrete steps.**

---

## 1. Scope

| In scope | Out of scope (unless linked doc expands) |
|----------|------------------------------------------|
| Persist-on path: transport → persistence writer → S3 → SQS ack/delete | Product UX unrelated to backup semantics |
| EKS-deployed workloads, in-cluster benchmarks | Laptop + port-forward as performance baseline |
| ConfigMap tuning, writer/SQS behavior, observability | Full security review of IAM (beyond persistence roles) |
| Escalation to async backup / Plan B (contract change) | Greenfield replacement of persistence design without DR |

---

## 2. Current technical picture (summary)

- **Durability contract:** Segment object is written to S3 **before** the checkpoint object is advanced (`persistence_writer` flush path). Any architecture change must preserve or explicitly redefine crash semantics.
- **Measured signal (P12.9):** Writer-visible **ack/delete latency and queue depth** dominated samples where **S3 segment and checkpoint PUTs** were comparatively small (tens to low hundreds of ms). **Do not** assume S3 is the primary bottleneck without fresh **`writer_snapshot`** / peak metrics after transport tuning.
- **Coupling:** L2 and worker paths **`await` transport publish** in places; end-to-end admission can remain bound even if the writer is healthy.

---

## 3. Platform and organizational constraints

- **IAM:** The deployment account’s principal used for CLI may carry **AdministratorAccess** while **AWS Organizations SCPs** still apply **explicit denies** on some APIs (e.g. **ECS**, **Service Quotas** list operations have been observed blocked by a specific SCP). Designs must not **depend** on denied services without org alignment.
- **Execution norm (workspace):** Full-flow load validation is **in-cluster on AWS** (Kubernetes Job, in-cluster URLs), not laptop-driven port-forward **for throughput claims**.
- **Hygiene:** **Full stack recycle** after persistence-related ConfigMap or image changes before benchmark runs, unless a maintainer narrows scope and labels results accordingly.

---

## 4. Strategic priorities (ordered)

1. **Prove where time goes** — Use **`writer_snapshot`** peaks: `ack_latency_ms`, `ack_queue_depth`, `receive_many` (interpret max vs long poll), `s3_segment_put_*`, `checkpoint_put_*`, shard-level skew.
2. **Transport and writer Plan A** — Ack concurrency, flush cadence, receive parallelism, producer `max_inflight` / batch behavior; one coherent knob bundle per **`iter-N`**.
3. **Shard / queue fairness** — If one logical shard hogs work, scaling replicas **without** routing fixes will not linearly improve throughput.
4. **S3 and encryption** — Only after (1)–(3): VPC endpoint hygiene, SSE-S3 vs SSE-KMS measurement, then optional **Express One Zone** / multipart if object size and AZ/durability tradeoffs justify.
5. **Plan B (async backup / ack contract)** — Only with **product + ops sign-off**; see decision record and Plan B doc below.

---

## 5. Phased roadmap

### Phase A — Baseline and measurement lock

| Goal | Activities | Exit criteria |
|------|------------|----------------|
| Comparable baselines | Align image tag across API, workers, writers, load-test Job; follow **`P12_9_AI_SE_PLAN_D_EKS_BENCHMARK_EXECUTION.md`** and **`P12_9_ITER6_TEST_EXECUTION_SPEC.md`** where still normative. | One archived **`iter-N`** with frozen artifact set documented. |
| Understand skew | Inspect writer metrics per **shard**; correlate with routing from L2/worker. | Hypothesis on skew **confirmed or ruled out** with numbers. |

**Canonical references:** `P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md`, `P12_9_MEASUREMENT_LOCK_REPORT.md`, `P12_9_SESSION_RECOVERY_PLAN.md`.

### Phase B — Plan A: transport and writer tuning

| Goal | Activities | Exit criteria |
|------|------------|----------------|
| Reduce ack pressure | Tune **`INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY`** and related writer keys per **`P12_9_AI_SE_PLAN_A_TRANSPORT_WRITER_TUNING.md`** and **`settings.py`** / ConfigMap. | Gates in throughput spec **pass** or next knob documented as **no improvement** with snapshot proof. |
| Align pipeline | Flush loop sleep, receive parallelism, ack queue bounds — **one bundle per iter**. | `ack_latency_ms` / depth **flat or improved** without regression on backup correctness. |

**Canonical references:** `P12_9_AI_SE_PLAN_A_TRANSPORT_WRITER_TUNING.md`, `P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md`, `P12_9_WS3_4_WRITER_PIPELINE_REPAIR_SPEC.md`.

### Phase C — Producer and hot-path coupling

| Goal | Activities | Exit criteria |
|------|------------|----------------|
| Cap publish storms | Review **`SqsPersistenceTransportProducer`** retry and **`max_inflight`** behavior; L2/worker **`await emit`** paths. | Publish path ruled in or out as throttle via metrics + load test. |

**Canonical references:** Timing plan §Finding 4, `routes.py` / `scheduler.py` (code), `P12_9_LAG_LOCALIZATION_PLAN.md`.

### Phase D — S3 and networking (conditional)

| Goal | Activities | Exit criteria |
|------|------------|----------------|
| Remove avoidable latency | Confirm **VPC gateway endpoint** for S3 on EKS paths; document bucket region vs cluster region. | **Captured:** `P12_9_EKS_S3_NETWORK_PATH.md` (same-region bucket; **no** gateway endpoint at capture — NAT egress). Re-validate after endpoint changes. |
| Encryption trade | If SSE-KMS on hot objects, A/B **p99 PUT** vs SSE-S3 where policy allows. | Decision recorded with metric delta. |
| Advanced S3 | **Multipart** only if segment sizes warrant; **S3 Express One Zone** only if latency/request rate and **single-AZ** semantics are accepted. | ADR or plan addendum with durability statement. |

**Canonical references:** `src/inspectio/v3/persistence_writer/s3_store.py`, `writer.py` flush contract.

### Phase E — Plan B (optional, gated)

| Goal | Activities | Exit criteria |
|------|------------|----------------|
| Decouple durability from user-visible path | Follow **`P12_9_AI_SE_PLAN_B_ASYNC_BACKUP_ACK_CONTRACT.md`**; align with **`P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md`**. | Explicit stakeholder approval; contract tests and load gates green. |

---

## 6. Decision gates (require explicit sign-off)

| Decision | Why it matters | Where to read |
|----------|----------------|---------------|
| Async backup / weaker synchronous guarantees | Changes user-visible failure and recovery semantics | `P12_9_AI_SE_PLAN_B_ASYNC_BACKUP_ACK_CONTRACT.md`, `P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md` |
| S3 Express One Zone or storage-class change | AZ failure exposure, replay assumptions | Addendum to Phase D; AWS docs |
| Org-dependent services (e.g. ECS, quota APIs) | SCP may block regardless of IAM admin | Org admin + SCP review |
| Observability investment level | Cost vs debug time under load | `P12_9_AI_SE_PLAN_C_OBSERVABILITY.md` |

---

## 7. Handoff index

For execution sequencing and file pointers, start with **`P12_9_AI_SE_HANDOFF_INDEX.md`**.

---

## 8. Review cadence (suggested)

- **After each `iter-N`:** Architect reviews snapshot peaks and gate results (R, completion ratio, backup checks).
- **Before Phase E:** Formal read of Plan B decision record and contract doc.
- **Quarterly or after major EKS/S3 change:** Re-validate §3 constraints (SCP, endpoints, encryption).

---

## 9. Execution status (living)

**As of 2026-04-04** — reconciles this document with archived P12.9 evidence and current infra.

### Completed or materially advanced

| Phase | Status | Evidence / notes |
|-------|--------|-------------------|
| **A** — Baselines | **Advanced** | `plans/v3_phases/artifacts/p12_9/iter-6/ITER6_RESULTS.md` remains the historical **NO-GO** baseline; **`iter-7` … `iter-13`** folders document subsequent methodology and promotions/regressions per `P12_9_AI_SE_HANDOFF_INDEX.md`. |
| **A** — Shard skew | **Partially closed** | **`iter-13-architect-phase-cd`**: **`shard_skew_summary.json`** + per-shard `writer_*_last_snapshot.log` — **mild** skew (e.g. logical shard **6** ~**20%** below max `receive_events_total`); not “one hot / rest idle”. See **`ITER13_ARCHITECT_PHASE_CD_RESULTS.md`**. |
| **B** — Plan A tuning | **Advanced** | EKS **Plan A** bundle experiments archived under **`iter-8-plan-a-perf`** through **`iter-12-flush-min-batch-80`** (ack delete concurrency, persist transport `max_inflight`, writer flush min batch). **`iter-12`** (**flush min batch 80**) reported **R ≈ 59%**, **PROMOTE** vs gates; repo **`deploy/kubernetes/configmap.yaml`** updated for promoted settings on that branch. **`iter-11`** (flush min 48) **NO-GO** — documented there. |
| **C** — Producer coupling | **Open (correlation)** | **Code:** L2 exposes **`GET /internal/persistence-transport-metrics`** when **`INSPECTIO_V3_EXPOSE_PERSISTENCE_TRANSPORT_METRICS=true`** (see **`P12_9_AI_SE_PLAN_C_OBSERVABILITY.md`**). **Caveat:** one **uvicorn worker** per response; aggregate via kubectl across API pods if needed. **Next:** re-run **`iter-N`** and correlate **`dropped_backpressure` / `publish_failures`** with **R**. **`iter-13`** predates this endpoint. |
| **D** — S3 / VPC path | **Applied (EKS)** | **`P12_9_EKS_S3_NETWORK_PATH.md`**: **S3 gateway endpoint** **`vpce-08ff97d249c7fad7b`** on **`vpc-0caf3ad198a12638f`** (2026-04-04) + route tables covering cluster subnets. Bucket remains **`us-east-1`**. |

### Infra / cost

- **EKS workers:** For **`iter-2026-04-04`**, **`ng-main`** was scaled **out** (8 → 16 nodes) to relieve **pod capacity** (e.g. **Redis** scheduling). For **cost pause**, scale again: `eksctl scale nodegroup --cluster nitzan-inspectio --region us-east-1 --name ng-main --nodes 0 --nodes-min 0`. See **`P12_9_SESSION_RECOVERY_PLAN.md`**.

### Next actions (recommended order)

1. **Phase C (close the loop)** — Use **`GET /internal/persistence-transport-metrics`** on **`inspectio-api`** (ConfigMap flag) during/after load; correlate with **`R`** on a new **`iter-N`**. Build/push image containing this route before EKS validation. References: **`P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md`** §Phase 3, **`P12_9_LAG_LOCALIZATION_PLAN.md`**, **`P12_9_AI_SE_PLAN_C_OBSERVABILITY.md`**.
2. **Phase D** — **S3 gateway endpoint** applied on **`nitzan-inspectio`** (see **`P12_9_EKS_S3_NETWORK_PATH.md`**). Re-measure **`R`** / writer PUT p99 on a new **`iter-N`** when you want a before/after number.
3. **Phase E** — **Hold** until Phase **C** is closed with numbers **or** the maintainer **explicitly waives** per **`P12_9_AI_SE_HANDOFF_INDEX.md`**.

### Branch / merge note

Implementation and artifact history for the **iter-8 … iter-12** Plan A line lived on **`feat/p12-9-plan-a-eks-perf`** (merge per maintainer backlog). Other lines (e.g. writer timing instrumentation on **`feat/p12-9-ai-se-plan-d-eks-benchmark`**) may need **rebase or cherry-pick** before a single canonical branch; see **`P12_9_SESSION_RECOVERY_PLAN.md`**.

---

*This plan was authored to consolidate architect-facing guidance; detailed step-by-step execution remains in the linked P12.9 documents.*
