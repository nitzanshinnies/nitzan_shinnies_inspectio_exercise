# P12.9 Lag localization plan

## Purpose

Pin **where time and throughput are lost** across admission, send-completion (promotion gate), and durability tail—without changing benchmark shape or tuning random knobs.

## Definitions (use consistently)

| Name | Meaning | Primary evidence |
|------|---------|------------------|
| **Admission throughput** | Client-observed admits over wall clock | `SUSTAIN_SUMMARY` in `off-allpods.log` / `on-allpods.log` |
| **Completion throughput (gate)** | Send-shard consumption rate | CloudWatch `AWS/SQS` `NumberOfMessagesDeleted`, send queues `inspectio-v3-send-0`…`7` |
| **Durability tail** | Event → S3 durable commit | Writer `writer_snapshot`: `lag_to_durable_commit_ms_max`, persist-queue oldest age |

## Phase 0 — Preconditions

1. Branch and image tag recorded (see `P12_9_SESSION_RECOVERY_PLAN.md`).
2. Config snapshot: `kubectl -n inspectio get configmap inspectio-v3-config -o json` → `configmap_snapshot.json`.
3. Full stack recycle before each profile (off/on), per `P12_9_ITER6_TEST_EXECUTION_SPEC.md`.

## Phase 1 — Local artifact triage (no AWS)

**Goal:** Decide whether the run is **valid** and whether lag shows up in **admission** before touching CloudWatch.

1. Confirm required files exist (see checklist in `scripts/v3_p12_9_lag_phase_analyze.py` output).
2. Parse `SUSTAIN_SUMMARY` for off/on: `admitted_total`, `offered_admit_rps`, `transient_errors` (if present).
3. Parse `off_job_status.json` / `on_job_status.json`: `succeeded==1`, `failed==0`.
4. Scan load logs for failure signatures: `HTTPStatusError`, `ReadError`, `500`, `BackoffLimitExceeded`, `Traceback`.

**Interpretation:**

- Job invalid → **no trustworthy completion ratio**; fix harness/stability first (matches Iter-6 SE notes).
- Off OK, on OK, similar `offered_admit_rps` → admission not the primary drop; move to Phase 2.
- On `offered_admit_rps` << off → include **L2 `emit_enqueued`** path and API capacity in hypothesis set.

**Automation:** run from repo root:

```bash
python scripts/v3_p12_9_lag_phase_analyze.py \
  --art-dir plans/v3_phases/artifacts/p12_9/iter-6
```

Use `--strict` to require all eight timestamp/log/job files (fails if e.g. `on_end.txt` is missing after an incomplete run).

## Phase 2 — CloudWatch completion (gate metric)

**Goal:** Measure **B** (send-queue deletes) for off vs on windows.

1. Ensure `off_start.txt`, `off_end.txt`, `on_start.txt`, `on_end.txt` bracket the load windows.
2. Run hygiene script (requires AWS credentials with CloudWatch read + correct region):

```bash
python scripts/v3_p12_9_iter3_rerun_hygiene.py \
  --art-dir plans/v3_phases/artifacts/p12_9/iter-6 \
  --image "<full ECR image from job>" \
  --cluster-context "$(kubectl config current-context)" \
  --namespace inspectio \
  --region us-east-1 \
  --period-sec 60 \
  --preload-sec 60 \
  --tail-sec 120 \
  --stat Sum
```

3. Read `cw_metrics.json`: `completion_ratio_percent_on_over_off`, `validity_checks`, `on`/`off` `combined_avg_rps`.

**Interpretation:**

- Ratio low, hygiene valid, Phase 1 shows similar admission → bottleneck is **worker publish+delete path** (two awaited persist publishes per completion) or **worker/expander capacity**.
- Ratio low with admission drop → split between **L2** and **worker**.

## Phase 3 — SQS queue depth and age (AWS console or CLI)

**Goal:** Separate **producer backlog** from **consumer lag**.

During each window, for **bulk**, **each send shard**, **each persist transport queue**:

- `ApproximateNumberOfMessagesVisible`
- `ApproximateAgeOfOldestMessage`

**Pattern:**

- Send queue depth/age grows in **on** vs **off** → workers not keeping up with expander (or delete delayed by persist publish).
- Persist queue depth/age grows while send queue flat → **writer/S3/ack** behind **publish** rate.
- Bulk queue backs up → expander or downstream starved.

## Phase 4 — Writer and pipeline evidence

**Goal:** Characterize **durability tail (C)**.

1. Collect writer logs; extract `writer_snapshot` lines → `writer_snapshot_extract.json` (per execution spec).
2. Compare `lag_to_durable_commit_ms_max`, `ack_queue_depth_high_water_mark`, `ack_queue_blocked_push_total`, `pipeline_mode`.

**Interpretation:**

- **C** healthy but **B** bad → do not prioritize writer flush tuning for the completion gate.
- **C** degraded (high lag, blocked pushes, deep queue) → writer/S3/ack tuning or capacity.

## Phase 5 — Targeted causality experiments (optional, lab only)

Only after Phases 1–4; keep benchmark shape identical; document in `ITER6_RESULTS.md` or a short addendum.

| Experiment | Hypothesis tested |
|------------|-------------------|
| `INSPECTIO_V3_PERSIST_DURABILITY_MODE=best_effort` vs `strict` | Inflight / publish failure blocking delete path |
| Adjust `INSPECTIO_V3_PERSIST_TRANSPORT_MAX_INFLIGHT` | Producer backpressure vs drops |
| `INSPECTIO_V3_TRY_SEND_ALWAYS_SUCCEED=false` (short run) | Event amplification via retry emits |

## Phase 6 — Optional instrumentation (if still ambiguous)

1. Periodic JSON log of `PersistenceTransportMetrics` (worker + L2 producer): `published_ok`, `dropped_backpressure`, `publish_failures`.
2. Structured timing spans: `enqueue_ms`, `emit_enqueued_ms`, `publish_attempt_result_ms`, `delete_ms` for sampled `message_id`.

## Stop conditions

- **Phase 1** fails job validity → stop; fix run, do not interpret ratio.
- **Phase 2** invalid hygiene → stop; fix windows or CW query, do not promote.
- **Phases 1–4** agree on a single dominant bucket (L2 vs worker vs writer vs invalid run) → write one-paragraph root-cause summary with evidence pointers.

## References

- `plans/v3_phases/P12_9_ITER6_TEST_EXECUTION_SPEC.md`
- `scripts/v3_p12_9_iter3_rerun_hygiene.py`
- ConfigMap knob map: prior architect handoff / `deploy/kubernetes/configmap.yaml`
