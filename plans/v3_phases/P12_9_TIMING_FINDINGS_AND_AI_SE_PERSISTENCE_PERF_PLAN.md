# P12.9 — Persistence timing findings + AI SE implementation plan

## Purpose

1. **Record** what we inferred from **measured persistence timings** (EKS `writer_snapshot` artifacts + prior iter-6 evidence).
2. Provide a **detailed, ordered implementation plan** an **AI SE** can execute: ConfigMap tuning, optional code, benchmarks, and escalation to Plan B.

**Normative execution** for benchmarks and hygiene remains **`P12_9_ITER6_TEST_EXECUTION_SPEC.md`** + **`P12_9_AI_SE_PLAN_D_EKS_BENCHMARK_EXECUTION.md`**. This document **adds interpretation and task ordering**; it does not replace gates or measurement protocol.

---

## Evidence sources (read in this order)

| Source | Location | What it shows |
|--------|----------|----------------|
| Iter-6 gate failure (baseline narrative) | `plans/v3_phases/artifacts/p12_9/iter-6/ITER6_RESULTS.md` | Completion ratio **NO-GO**; admit on/off ~**58.5%**. |
| Iter-6 writer under load | `plans/v3_phases/artifacts/p12_9/iter-6/writer_snapshot_extract.json` | **`ack_queue_depth` ~350–500**, **`ack_latency_ms` ~0.8–2s**, `pipeline_mode: decoupled_v1`. |
| Post-instrumentation EKS sample | `plans/v3_phases/artifacts/p12_9/writer-metrics-20260403/WRITER_METRICS_PEAKS.json` | Peaks: **`ack_latency_ms` ~1.5–2.6s** per writer deploy; **`receive_many_duration_ms_max` ~12–20s**; **S3 segment put** max **~109ms**, **checkpoint** max **~51ms** on one shard with non-zero flush activity. |
| Full snapshot series | `.../writer_snapshots_extracted.jsonl` | Time series for new fields: `avg_receive_many_ms`, `s3_segment_put_duration_ms_*`, `checkpoint_put_duration_ms_*`, `receive_many_*`. |
| Architecture coupling (code) | `src/inspectio/v3/l2/routes.py`, `src/inspectio/v3/worker/scheduler.py` | **`await` persistence transport publish** on admit / before send-queue delete — not visible in writer JSON alone but affects **end-to-end** persist-on RPS. |

**Image used for timing capture (historical):** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-writer-metrics-20260403033555` (see frozen state in `P12_9_SESSION_RECOVERY_PLAN.md`).

---

## Documented findings

### Finding 1 — Transport ack/delete dominates writer-visible latency (not S3 PUT)

**Observation:** In `WRITER_METRICS_PEAKS.json`, **`ack_latency_ms`** peaks are on the order of **~1.5–2.6 seconds** across writer deployments, while **S3 segment** and **checkpoint** stage maxima (where non-zero) are **~100ms and ~50ms** respectively.

**Interpretation:** For the persistence **writer process**, the **bottleneck signal** in these samples is **finishing transport message deletion** (`DeleteMessage` / batch) after flush, not **uploading segment bytes** to S3. This **aligns** with iter-6’s **`ack_queue_depth`** and **`ack_latency_ms`** narrative.

**Implication:** Prioritize **ack throughput** (concurrency, batching, queue depth, loop cadence) before chasing **micro-optimizations on gzip/PUT** alone.

---

### Finding 2 — `receive_many` max ~12–20s is consistent with SQS long polling, not “broken receive”

**Observation:** `receive_many_duration_ms_max` peaks ~**12–20s** while **`avg_receive_many_ms`** stays in the **tens of milliseconds** when the queue is busy.

**Interpretation:** The **max** is dominated by **long-poll wait** on empty or sparse polls. This is **expected** for configured wait time, not proof that receive is the system throttle.

**Implication:** Do **not** “fix” by blindly shortening long poll without measuring **empty-poll rate** and **SQS API cost**; focus optimization on **post-receive** pipeline (ingest → flush → ack).

---

### Finding 3 — Possible skew of logical `shard` / uneven flush load across writer pods

**Observation:** In the same window, **most** writer deploys showed **zero** max for **S3 segment / flush** in peaks, while **one** deploy (e.g. shard-4) showed **non-zero** segment and checkpoint timings.

**Interpretation (hypothesis):** **Persistence events** may be **concentrated** on a small subset of **logical `shard` values** (routing from L2/worker), so **one transport queue + one writer** does most **S3 + checkpoint** work while others are mostly idle or ack-heavy.

**Implication:** Treat **shard distribution** as a **first-class diagnostic**. If skew is real, **scaling replicas** without fixing routing **will not** linearly improve throughput.

---

### Finding 4 — Upstream `await` on transport publish still couples “hot path” to persistence ingress

**Observation (code review):** L2 **`await emit_enqueued`** after bulk enqueue; worker **`await` emitter** before **send-queue delete** on terminal paths.

**Interpretation:** Even when the **writer** is fast, **admission** and **send completion** can lag if **transport publish** is slow or contended (`SqsPersistenceTransportProducer` retries, throttling, `max_inflight`).

**Implication:** If Plan A writer/ack tuning **plateaus**, **Plan B** (ack contract / decouple publish from send delete or HTTP response) is the **architectural** lever — requires **explicit product sign-off** (`P12_9_AI_SE_PLAN_B_ASYNC_BACKUP_ACK_CONTRACT.md`).

---

## Implementation plan for AI SE

### Preconditions (block until satisfied)

- [ ] **Branch** and **image tag** agreed with maintainer; **same `IMG`** for off leg, on leg, Job, and all non-redis Deployments for each **`iter-N`**.
- [ ] **`pytest`** scope green locally (minimum: `P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md` §Tests + any modules touched).
- [ ] **Cluster:** `kubectl` context correct; **`inspectio-v3-config`** exists; **`INSPECTIO_V3_PERSIST_EMIT_ENABLED`** toggled only with **full stack recycle** after each change.
- [ ] **Baseline:** Either accept **iter-6** as historical baseline **or** run **Plan D** once to produce fresh **`iter-N`** before tuning (recommended if cluster/image drifted).

---

### Phase 1 — Ack path throughput (highest priority)

**Goal:** Reduce **`ack_latency_ms`** and **`ack_queue_depth`** under persist-on load without violating writer contracts.

| Step | Task | Detail |
|------|------|--------|
| 1.1 | **Confirm ConfigMap key present** | `kubectl -n inspectio get cm inspectio-v3-config -o jsonpath='{.data.INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY}'` — if empty, **add** key (default in repo template is **`"8"`** in `deploy/kubernetes/configmap.yaml`). |
| 1.2 | **Tune ack delete concurrency** | Range **1..8** (clamped in `sqs_consumer.py`). Default **`8`** validated on EKS (**iter-9-ack8**). If regressions appear, step **down** with one **Plan D** **`iter-N`** per value and document. |
| 1.3 | **Recycle after ConfigMap change** | **Default:** **full stack recycle** (all app Deployments that read `inspectio-v3-config`, not writers alone) after each persistence-related CM trial — matches **`P12_9_AI_SE_PLAN_A`** A.1 step 3 and workspace **`restart-containers-before-inspectio-tests`**. Writer-only rollout is **only** for a maintainer-narrowed experiment and must be **labeled** in **`ITERn_RESULTS.md`** so results are not compared apples-to-apples with full-recycle runs. |
| 1.4 | **Capture evidence** | For each trial: **`writer_snapshot_extract.json`**, peaks for **`ack_latency_ms_max`**, **`ack_queue_depth_high_water_mark`**, and hygiene **R** / gate-2. |
| 1.5 | **Stop condition** | Stop when **gates pass** or **no further improvement** in **ack** metrics / **R** at next concurrency step (document negative result in **`ITERn_RESULTS.md`**). |

**Code touchpoints (read-only unless bug found):**

- `src/inspectio/v3/persistence_writer/main.py` — `ack_delete_max_concurrency` → consumer.
- `src/inspectio/v3/persistence_transport/sqs_consumer.py` — concurrency clamp.
- `src/inspectio/v3/settings.py` — `persistence_ack_delete_max_concurrency`.

**Canonical supplement:** **`P12_9_AI_SE_PLAN_A_TRANSPORT_WRITER_TUNING.md`** Tasks that mention ack concurrency and decoupled pipeline.

---

### Phase 2 — Writer pipeline cadence (Plan A remainder)

**Goal:** Align **flush batching**, **flush loop sleep**, **receive parallelism**, and **ack queue bound** so flush produces fewer, healthier ack batches without blowing memory.

| Step | Task | Detail |
|------|------|--------|
| 2.1 | **Apply Plan A task order** | Follow **`P12_9_AI_SE_PLAN_A_TRANSPORT_WRITER_TUNING.md`** for **`INSPECTIO_V3_PERSISTENCE_WRITER_*`**, **`INSPECTIO_V3_WRITER_FLUSH_LOOP_SLEEP_MS`**, **`INSPECTIO_V3_WRITER_RECEIVE_LOOP_PARALLELISM`**, **`INSPECTIO_V3_WRITER_ACK_QUEUE_MAX_EVENTS`**, and related keys as written there (use **exact** ConfigMap names from **`deploy/kubernetes/configmap.yaml`** / **`settings.py`**). |
| 2.2 | **One bundle per iter-N** | Do **not** change ten knobs in one Job; group **coherent** changes and archive **`iter-N`** per bundle. |
| 2.3 | **Interpret new timing fields** | Use **`avg_s3_segment_put_ms`**, **`avg_checkpoint_put_ms`**, **`flush_duration_ms_last`** in `writer_snapshot` to see if S3/checkpoint **grows** into a bottleneck **after** ack improves. |

**Stop condition:** Gates pass **or** Plan A matrix **exhausted** (table in **`ITERn_RESULTS.md`**).

---

### Phase 3 — Producer / emitter pressure (L2 + worker)

**Goal:** Ensure **transport publish** is not throttling before the writer (`max_inflight`, batch size, retry storms).

| Step | Task | Detail |
|------|------|--------|
| 3.1 | **Config sweep** | Tune **`INSPECTIO_V3_PERSIST_TRANSPORT_*`** (`max_inflight`, batch max, backoff) per **`settings.py`** / **`P12_9_AI_SE_PLAN_A`** emitter section. |
| 3.2 | **Observe** | **`PersistenceTransportMetrics`** in code (`publish_duration_ms_*`, `dropped_backpressure`, `publish_failures`) — if not logged, add **Plan C** logging or temporary DEBUG (maintainer-approved). |
| 3.3 | **Benchmark** | Re-run Plan D; compare **admit RPS** vs **completion RPS** gap. |

---

### Phase 4 — Shard distribution diagnostic (conditional)

**Trigger:** Phase 1–3 show **persistent idle** writers (zero flush activity) alongside **one hot** writer **or** uneven **`shards`{}** keys in snapshots.

| Step | Task | Detail |
|------|------|--------|
| 4.1 | **Measure** | From **`writer_snapshots_extracted.jsonl`** or live logs: distribution of **logical `shard`** on events **or** per-queue **ApproximateNumberOfMessagesVisible** on **persist-transport** queues. |
| 4.2 | **If skew confirmed** | **Routing / shard-assignment code changes** (L2 **`predicted_shard_index`**, worker envelope, hash policy) are **out of scope** for default WS3 tuning per **`P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md`** §Out of scope (items **3–4**) unless the maintainer **explicitly waives**. Document skew evidence and file a **follow-up** / Plan B discussion; do **not** ship routing changes under “Plan A ConfigMap tuning” without that waiver. |

---

### Phase 5 — Plan B (explicit escalation)

**Trigger:** **`P12_9_AI_SE_PLAN_A`** is **documented exhausted** in **`ITERn_RESULTS.md`** (tasks **A.1–A.4** as applicable, including the timing-plan Phase **1–3** sweeps), **and** if Phase **4** applied, its **diagnostic conclusion** is recorded — **and** promotion **gates still fail**. This matches the handoff index rule: Plan B **after** Plan A exhausted, not merely after one failed ack sweep.

| Step | Task | Detail |
|------|------|--------|
| 5.1 | **Stop** | Do **not** implement early ack without **`P12_9_AI_SE_PLAN_B_ASYNC_BACKUP_ACK_CONTRACT.md`** **Task B.0** memo. |
| 5.2 | **Execute** | Follow Plan B path **B.1 / B.2 / B.3** per maintainer decision. |

---

## Acceptance criteria (per iteration)

1. **`iter-N`** folder: timestamps, job logs, job JSON, hygiene outputs, **`writer_snapshot_extract.json`**, **`ITERn_RESULTS.md`** with **R**, **(R − 44.84)**, ConfigMap diff, **`IMG`**.
2. **`writer_snapshot`** shows **`pipeline_mode`** and **ack** / queue fields. **Receive / S3 / checkpoint timing** fields appear only on images that include the writer timing instrumentation (see session recovery / image tag notes); their **absence** does not invalidate hygiene or gates if **pipeline_mode** and ack metrics are present.
3. **Gates:** **R ≥ 52.66%** and **(R − 44.84) ≥ 5 pp**; hygiene **`measurement_valid: true`**; jobs **succeeded=1**, **failed=0** per leg.
4. **Pytest** unchanged or expanded per diff; **no regression**.

---

## Tests (local, before merge)

Minimum set from **`P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md`** plus any new modules:

```bash
cd nitzan_shinnies_inspectio_exercise
pytest -q \
  tests/unit/test_v3_persistence_writer.py \
  tests/unit/test_v3_persistence_writer_main_observability.py \
  tests/unit/test_v3_settings_persistence_writer.py \
  tests/integration/test_v3_persistence_writer_fake_flow.py \
  tests/integration/test_v3_persistence_fault_injection.py \
  tests/unit/test_v3_persistence_transport_sqs_producer.py \
  tests/unit/test_v3_sustained_admit.py
```

---

## Rollback

- Revert ConfigMap to last known-good; **full stack recycle**.
- Image rollback per **`P12_9_ITER6_TEST_EXECUTION_SPEC.md`** Step 9 (maintainer tag).

---

## Entry point for AI SE

1. **`plans/v3_phases/P12_9_AI_SE_HANDOFF_INDEX.md`**
2. **This file** — findings + **Phase 1–5** order
3. **`P12_9_AI_SE_PLAN_A_TRANSPORT_WRITER_TUNING.md`** + **`P12_9_AI_SE_PLAN_D_EKS_BENCHMARK_EXECUTION.md`** for execution detail

---

## Changelog

| Date | Note |
|------|------|
| 2026-04-03 | Initial findings from `writer-metrics-20260403` + iter-6; phased plan for SE handoff. |
