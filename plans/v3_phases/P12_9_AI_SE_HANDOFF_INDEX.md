# P12.9 — AI SE implementation handoff (index)

## Purpose

Single entry point for a **software-engineering agent** (human or AI) implementing the next Inspectio v3 persistence / throughput work. Each linked plan is **self-contained**: prerequisites, tasks, tests, acceptance criteria, and rollback.

**Path convention:** all repo-relative paths below assume the repository root (e.g. `plans/v3_phases/...`).

## Product and architecture locks (read first)

| Document | Role |
|----------|------|
| `plans/v3_phases/P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md` | **Intent:** S3 = async backup; scheduler = memory + SQS; throughput before durability tightening. |
| `plans/v3_phases/P12_DECISION_RECORD.md` | **Writer contracts:** segment-before-checkpoint, transport ordering, reducer monotonicity. |
| `plans/v3_phases/P12_9_WS3_4_WRITER_PIPELINE_REPAIR_SPEC.md` | **Implemented** decoupled writer pipeline (`decoupled_v1`); do not regress without spec update. |
| `plans/v3_phases/P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md` | **SE fix contract** after pipeline repair: phase-1 tuning → gates; phase-2 Plan B only if approved. |
| `plans/v3_phases/P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md` | **Timing findings** (writer_snapshot + iter-6) + **phased SE plan**: ack concurrency → Plan A → emitter → shard skew → Plan B. |

## Evidence baseline (what failed the gate)

| Artifact | Use |
|----------|-----|
| `plans/v3_phases/artifacts/p12_9/iter-6/ITER6_RESULTS.md` | Hygiene-valid **NO-GO** (WS3 narrative baseline): completion ratio ~**47.72%** vs gate **52.66%**; admit on/off ~**58.5%**. |
| `plans/v3_phases/artifacts/p12_9/iter-6/writer_snapshot_extract.json` | Under load: **`ack_queue_depth` ~350–500**, **`ack_latency_ms` ~0.8–2s**, `pipeline_mode: decoupled_v1`. |
| `plans/v3_phases/artifacts/p12_9/iter-7/ITER7_RESULTS.md` (if present) | Example **PROMOTE** on a later image/config — use for **methodology** and folder layout; do **not** assume it supersedes iter-6 as the “problem statement” unless the maintainer says so. |

## When to run which plan (decision tree)

- **No fresh A/B after your last code or ConfigMap change** → run **Plan D** first (`iter-N` folder), then tune.
- **iter-6 (or latest) artifacts are accepted as baseline** and you only change **ConfigMap** with **same image** → you may run **Plan A** and benchmark using Plan D’s checklist **without** re-copying the whole spec—still produce a **new `iter-N`** per change bundle so evidence is not overwritten.
- **Timing-driven priority** (ack vs S3 vs long-poll vs shard skew) → read **`P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md`** before sweeping knobs; it orders **Phase 1 ack concurrency** ahead of micro S3 tuning.
- **Plan C** may run **in parallel with Plan A** (metrics help interpret tuning) but must not block shipping tuning PRs.
- **Plan B** only after Plan A is **documented exhausted** (table in `ITERn_RESULTS.md`) or explicitly waived by maintainer.

## Recommended default order (if starting cold)

| Order | Plan file | Summary |
|-------|-----------|---------|
| **1** | `P12_9_AI_SE_PLAN_D_EKS_BENCHMARK_EXECUTION.md` | Baseline or post-change A/B; archive **`plans/v3_phases/artifacts/p12_9/iter-N/`**. |
| **2** | `P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md` | **Read before broad Plan A sweeps:** metrics findings + phased task list (ack → writer → emitter → skew → Plan B); required rationale is also summarized in **`P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md`** §Fix phase 1. |
| **3** | `P12_9_AI_SE_PLAN_A_TRANSPORT_WRITER_TUNING.md` | ConfigMap + bounded code tuning; re-run D after each coherent bundle. |
| **4** | `P12_9_AI_SE_PLAN_C_OBSERVABILITY.md` | Metrics map + optional counters/script/runbook. |
| **5** | `P12_9_AI_SE_PLAN_B_ASYNC_BACKUP_ACK_CONTRACT.md` | Ack-timing / architecture fork; requires explicit path + failure-mode memo. |

## Canonical benchmark (do not drift)

- **Shape:** `--duration-sec 240 --concurrency 120 --batch 200`, L1 base `http://inspectio-l1:8080`, persist off then on (order **fixed**: off first, on second).
- **Same candidate image** for **both** legs and the Job pods (`IMG`); document tag in `ITERn_RESULTS.md`.
- **Completion metric:** CloudWatch `AWS/SQS NumberOfMessagesDeleted`, **Sum**, **60s** period, summed over **`inspectio-v3-send-0` … `inspectio-v3-send-7`** (exact queue names in `scripts/v3_p12_9_iter3_rerun_hygiene.py`).
- **Hygiene:** `scripts/v3_p12_9_iter3_rerun_hygiene.py` with parameters matching `P12_9_ITER6_TEST_EXECUTION_SPEC.md` Step 5.
- **Normative procedure:** `P12_9_ITER6_TEST_EXECUTION_SPEC.md` (adapt **only** `ART`, job names, and completeness-check path for `iter-N`).

## Promotion gates (from WS3 handoffs; both must pass)

Let **R** = persist-on **combined_avg_rps** ÷ persist-off **combined_avg_rps** × **100** (same definition as hygiene script: `completion_ratio_percent_on_over_off`).

Until explicitly renegotiated, **completion-ratio gates** (report **both** in `ITERn_RESULTS.md`; hygiene **`decision: PROMOTE`** is **only** the first):

1. **R ≥ 52.66** (completion ratio percent on/off).
2. **(R − 44.84) ≥ 5.00** (gain vs WS3.1 baseline completion ratio **44.84%**, in percentage points).

**Note:** With baseline **44.84**, item **2** implies **R ≥ 49.84%**, so item **1** (**R ≥ 52.66%**) is **stricter**; still compute and record **both**.

**Also required (not implied by hygiene `PROMOTE`):**

3. Jobs: `succeeded=1`, `failed=0` per leg; hygiene output **`measurement_valid: true`**.
4. **Correctness:** no regression vs agreed pytest scope (see Plan A / Plan D).
5. **Pipeline evidence:** `writer_snapshot_extract.json` present with `pipeline_mode` and queue/ack fields (per `P12_9_ITER6_TEST_EXECUTION_SPEC.md` Step 6).

### Hygiene script vs gates (important)

`scripts/v3_p12_9_iter3_rerun_hygiene.py` sets **`"decision": "PROMOTE"`** only when **`completion_ratio_percent_on_over_off` ≥ 52.66** (and validity checks pass). It does **not** evaluate **gate 2** (**(R − 44.84) ≥ 5**). **SE must compute gate 2** from **`cw_metrics.json`** (same **R** field) or the script’s printed JSON and record both in **`ITERn_RESULTS.md`**.

## Repo and branch

- **Default** implementation branch: **`feat/v3-p12-9-tuning-iter-6-writer-pipeline`** (or successor from maintainer).
- A **session-specific** branch (e.g. timing instrumentation + EKS benchmark) may differ — see **`P12_9_SESSION_RECOVERY_PLAN.md`** “Frozen handoff state” if you are resuming that session; merge or rebase per maintainer before treating branch as canonical.
- **In-repo** Cursor rule: **`nitzan_shinnies_inspectio_exercise/.cursor/rules/inspectio-testing-and-performance.mdc`** (v3 testing + in-cluster performance discipline).
- **Antigravity workspace** (parent of repo): **`antigravity_ws/.cursor/rules/`** may also define **`inspectio-full-flow-load-test-aws-in-cluster.mdc`**, **`restart-containers-before-inspectio-tests.mdc`**, **`inspectio-eks-agent-executes-deploy.mdc`** — follow those when present (full stack recycle before benchmarks; load driver in-cluster for AWS throughput claims).

## Session recovery (human context)

- `plans/v3_phases/P12_9_SESSION_RECOVERY_PLAN.md` — resume checklist, stale infra warnings.

## Runbooks (after Plan C)

- `plans/v3_phases/P12_9_OBSERVABILITY_RUNBOOK.md` — SE triage (completion vs backup vs admit); extend per **Plan C** when new metrics/scripts land.

---

**Start here:** **`P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md`** (fix contract) → **`P12_9_AI_SE_PLAN_D_EKS_BENCHMARK_EXECUTION.md`** when you need a fresh **`iter-N`** → read **`P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md`** for measured rationale and phase order → **`P12_9_AI_SE_PLAN_A_TRANSPORT_WRITER_TUNING.md`** for knob-level tasks (ack concurrency **A.1** before flush **A.2**).
