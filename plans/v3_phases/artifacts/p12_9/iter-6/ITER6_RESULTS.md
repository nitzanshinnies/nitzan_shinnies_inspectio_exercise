# P12.9 WS3 Iteration 6 Results

## Candidate image and branch

- **Image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter6-20260402155642`
- **Branch:** `feat/v3-p12-9-tuning-iter-6-writer-pipeline`
- **Scope:** Writer pipeline decoupling (`decoupled_v1`); benchmark shape unchanged vs canonical spec.

## Config under test

From `configmap_snapshot.json` after the persist-on leg (persist emit on):

- `INSPECTIO_V3_PERSIST_EMIT_ENABLED=true`
- `INSPECTIO_V3_PERSIST_DURABILITY_MODE=best_effort`
- `INSPECTIO_V3_PERSIST_TRANSPORT_SHARD_COUNT=8` (eight transport queue URLs)
- `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_INTERVAL_MS=2000`
- `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS=64`
- Writer pipeline env overrides for `INSPECTIO_V3_WRITER_PIPELINE_ENABLE` / flush-loop sleep were **not** set in ConfigMap; **defaults from the image** apply.

## Admission summary (driver)

Source: `sustain_summaries.json` / `SUSTAIN_SUMMARY` lines in pod logs.

| Profile | admitted_total | duration_sec | offered_admit_rps | transient_errors |
|---------|----------------|-------------|-------------------|------------------|
| Persist **off** | 1,596,600 | 240.0 | **6652.50** | 5 |
| Persist **on** | 934,400 | 240.0 | **3893.33** | 1 |

- **Admission ratio (on/off):** `3893.33 / 6652.50` ≈ **58.5%**

## Completion summary (CloudWatch)

Source: `measurement_manifest.json`, `cw_metrics.json`; metric `AWS/SQS NumberOfMessagesDeleted` summed across `inspectio-v3-send-0..7`, period **60s**, stat **Sum**, hygiene windows per `v3_p12_9_iter3_rerun_hygiene.py`.

| Profile | combined_avg_rps | combined_peak_rps | active_periods | datapoints |
|---------|------------------|-------------------|----------------|------------|
| Persist **off** | **3801.43** | 6763.08 | 5 | 7 |
| Persist **on** | **1813.88** | 3320.43 | 6 | 7 |

- **Completion ratio (on/off):** `1813.88 / 3801.43` ≈ **47.72%**
- **Gain vs WS3.1 baseline completion ratio (44.84%):** `47.72 - 44.84` ≈ **+2.88 pp** (requires **+5.00 pp** for promotion gate)

## Hygiene validity

From hygiene script output / `measurement_manifest.json`:

- `measurement_valid`: **true**
- `datapoint_count_difference`: **0** (≤ 1)
- `off_active_periods_gte_5`, `on_active_periods_gte_5`: **true**
- `period_is_60s`, `stat_is_sum`: **true**
- Job validity: off **succeeded=1, failed=0**; on **succeeded=1, failed=0**; single attempt each.

## Pipeline evidence (`writer_snapshot`)

- **Artifact:** `writer_snapshot_extract.json` (105 lines from `inspectio-persistence-writer-shard-*.log`).
- **Mode:** `pipeline_mode: "decoupled_v1"` present on sampled lines.
- **Under load (persist-on window):** shard-0 logs show sustained receive/ack activity, e.g. `ingest_events_per_sec` on the order of **40–168**, `ack_queue_depth_current` often **~350–500**, `ack_latency_ms_last` up to **~1.3–2.0s**, `queue_polling_idle_ratio` near **0** while loaded — consistent with a hot persistence path, not an idle writer.

## Decision gate evaluation

Per `P12_9_ITER6_TEST_EXECUTION_SPEC.md`:

1. Completion ratio **≥ 52.66%** → **FAIL** (**47.72%**)
2. Gain vs WS3.1 (**44.84%**) **≥ +5.00 pp** → **FAIL** (**+2.88 pp**)
3. Correctness / stability (pre-scope): jobs completed cleanly; hygiene valid → **PASS** for this run’s stability surface
4. Pipeline evidence present → **PASS**

## Outcome

**NO-GO** for promotion against the stated WS3 gates.

**Rollback:** Not applied automatically. Cluster remains on candidate image `p12-9-iter6-20260402155642` with `INSPECTIO_V3_PERSIST_EMIT_ENABLED=true` after the on leg. To revert image and config, follow spec Step 9 if desired.

## Artifacts

Required bundle per spec Step 8:

- Timestamps: `off_start.txt`, `off_end.txt`, `on_start.txt`, `on_end.txt`
- Logs: `off-allpods.log`, `on-allpods.log`
- Jobs: `off_job_status.json`, `on_job_status.json`
- Metrics: `sustain_summaries.json`, `cw_metrics.json`, `measurement_manifest.json`
- Pipeline: `writer_snapshot_extract.json`, writer shard logs `inspectio-persistence-writer-shard-*.log`
- Cluster snapshots: `deployments_snapshot.json`, `configmap_snapshot.json`

## Note on absolute RPS vs prior iterations

Average completion RPS in this run (off **~3801**, on **~1814**) is lower than e.g. Iteration 4’s report (~8053 / ~3585). The **ratio on/off** is the gate-relevant comparison; absolute levels can move with cluster load, node count, and queue state. This run used nodegroup **desired capacity 12** (`m5.large`).
