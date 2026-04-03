# P12.9 — SE fix spec: completion throughput + async-backup alignment

## Purpose

Give a **software engineer** (human or AI) a **single, ordered fix contract** after **writer pipeline decoupling** (`decoupled_v1`) is in place but **promotion gates still fail**.

This spec **does not** repeat the full WS3.4 pipeline repair (see `P12_9_WS3_4_WRITER_PIPELINE_REPAIR_SPEC.md`). It defines **what to do next** to move **persist-on / persist-off completion ratio** and related metrics toward gates, consistent with **`P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md`** (throughput first; backup may lag; scheduler stays memory + SQS).

## Canonical references (read order)

1. **Handoff index:** `plans/v3_phases/P12_9_AI_SE_HANDOFF_INDEX.md`
2. **Benchmark protocol:** `plans/v3_phases/P12_9_ITER6_TEST_EXECUTION_SPEC.md`
3. **Detailed plans:** `P12_9_AI_SE_PLAN_A` … `PLAN_D` (tuning, ack contract, observability, EKS execution)
4. **Timing findings + phased SE work order:** `plans/v3_phases/P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md`
5. **Baseline evidence:** `plans/v3_phases/artifacts/p12_9/iter-6/ITER6_RESULTS.md` (hygiene-valid NO-GO example)

## Problem statement (locked from iter-6)

| Metric | Observed (iter-6) | Gate |
|--------|-------------------|------|
| **Completion ratio R** (on avg RPS / off avg RPS × 100) | **~47.72%** | **≥ 52.66%** |
| **Gain vs 44.84% baseline** | **~+2.88 pp** | **≥ +5.00 pp** |
| **Admit ratio** (driver) | **~58.5%** | (diagnostic; not the completion gate) |

**Symptoms:** Under load, writer snapshots showed **`ack_queue_depth` ~350–500**, **`ack_latency_ms` ~0.8–2s**, `pipeline_mode: decoupled_v1` — consistent with **SQS delete / flush batching** pressure on the backup path, not “scheduler reads S3.”

## Preconditions (must be true before starting this spec)

- [ ] Image on cluster includes **decoupled writer pipeline** (`writer_snapshot` shows `decoupled_v1` under persist-on load).
- [ ] **`pytest`** green for persistence writer + settings + fake flow + sustained_admit (see §Tests below).
- [ ] You can run **Plan D** end-to-end (EKS Jobs + hygiene script + `measurement_valid: true`).

If any precondition fails, **stop** and fix that first; do not tune blind.

## Scope lock

### In scope

1. **ConfigMap / env tuning** on EKS: ack delete concurrency, flush min batch, flush interval, writer flush-loop sleep, receive parallelism, persistence emitter **`max_inflight`** / batch (within existing settings bounds).
2. **Small code changes** only when required to: raise caps safely, expose missing metrics, or fix bugs found during benchmark (with tests).
3. **Observability** per Plan C: metrics map, optional counters, runbook file **`P12_9_OBSERVABILITY_RUNBOOK.md`**.
4. **Documented** A/B runs: new **`plans/v3_phases/artifacts/p12_9/iter-N/`** + **`ITERn_RESULTS.md`** per change bundle.

### Out of scope (unless maintainer explicitly approves a Plan B memo)

1. **Early transport ack before S3** (changes durability story; requires `P12_9_AI_SE_PLAN_B` + failure-mode sign-off).
2. **Gate threshold changes** (52.66%, +5 pp).
3. **L2 / API / scheduler algorithm** changes.
4. **Shard count** or queue topology changes without infra review.

## Fix phase 1 — Throughput tuning (do this first)

Execute **`P12_9_AI_SE_PLAN_A_TRANSPORT_WRITER_TUNING.md`** in the **task order** written there (**A.1** ack-delete concurrency **before** **A.2** flush sweep). Rationale and extended phase ordering (producer pressure, shard skew diagnostic, Plan B trigger) are in **`P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md`** — use it so tuning stays evidence-led and does not violate §Out of scope (e.g. routing changes) without a maintainer waiver.

**Minimum SE deliverables:**

1. Table in **`ITERn_RESULTS.md`**: for each trial, **R**, **(R − 44.84)**, admit ratio, **ConfigMap diff** (keys + values), **image tag**, **iter-N** folder path.
2. **`writer_snapshot_extract.json`** for the persist-on leg of the **best** trial.
3. Hygiene **`measurement_valid: true`** for that trial.

**Stop phase 1 when:**

- **R ≥ 52.66** and **(R − 44.84) ≥ 5**, or
- A **signed-off** matrix shows **no further gain** from Plan A knobs (document negative results; then escalate to Plan B).

## Fix phase 2 — Async-backup / ack contract (only if phase 1 fails gates)

Do **not** start until **`P12_9_AI_SE_PLAN_B_ASYNC_BACKUP_ACK_CONTRACT.md`** **Task B.0** decision memo is approved (path B.1 / B.2 / B.3 + accepted failure modes for `best_effort`).

Default preference: **Path B.2** (keep ack-after-S3; optimize I/O or shards) before **B.1** (early ack).

## Promotion criteria (all required)

1. **R ≥ 52.66** and **(R − 44.84) ≥ 5.00** (compute **R** from hygiene output; remember hygiene script **`decision`** is **gate-1 only** — see `P12_9_AI_SE_HANDOFF_INDEX.md`).
2. **`measurement_valid: true`**; jobs **`succeeded=1`**, **`failed=0`** per leg.
3. **No pytest regression** in §Tests.
4. **`writer_snapshot_extract.json`** shows expected **`pipeline_mode`** and ack/queue fields.
5. **PR description** links **`iter-N`** results and summarizes ConfigMap vs code changes.

## Tests (local, before every merge)

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

If you touch emitter, worker persistence wiring, or transport producer internals, add or run any **`tests/`** that cover those modules per `git diff`.

## Operational invariants (invalidate evidence if violated)

- **Same `IMG`** for off Job, on Job, and all non-redis Deployments for that **`iter-N`**.
- **Persist-off leg before persist-on**; **full stack recycle** after each **`INSPECTIO_V3_PERSIST_EMIT_ENABLED`** change.
- Load driver **in-cluster**; **no laptop port-forward** for performance claims (see in-repo `.cursor/rules/inspectio-testing-and-performance.mdc`).

## Rollback

- Revert ConfigMap to last known-good; **recycle full stack**.
- Image rollback pattern: `P12_9_ITER6_TEST_EXECUTION_SPEC.md` Step 9 (adjust image tag as directed by maintainer).

## Definition of done

- Gates met **or** explicit **NO-GO** with **iter-N** evidence and **written** conclusion that Phase 2 is required.
- This spec’s **phase 1** table complete for the attempted iteration.

---

**Entry for SE:** start at `P12_9_AI_SE_HANDOFF_INDEX.md`, then execute **Phase 1** of **this** spec using Plan A + Plan D.
