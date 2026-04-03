# P12.9 Iteration 7 Results (deploy + sustain benchmark)

## Candidate image and branch

- **Image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-deploy-20260402183410`
- **Branch (workspace at run time):** `feat/p12-9-ai-se-plan-d-eks-benchmark` @ `a983530`
- **Jobs:** `inspectio-v3-p12-9-iter7-off`, `inspectio-v3-p12-9-iter7-on` (240s sustain, 120×200, in-cluster L1 URL)
- **Load Job pod spec:** `serviceAccountName: inspectio-app`, `imagePullPolicy: Always`, same `IMG` as all app Deployments.

## Config under test

From cluster `inspectio-v3-config` (persist-on leg ends with emit enabled):

- `INSPECTIO_V3_PERSIST_EMIT_ENABLED=true` after on leg (off leg used `false` before off job).
- Full stack **rollout restart** after each persist toggle, per `P12_9_ITER6_TEST_EXECUTION_SPEC.md`.

See `configmap_snapshot.json` in this folder for the captured ConfigMap at snapshot time.

## Admission summary (driver)

Source: `sustain_summaries.json` / `SUSTAIN_SUMMARY` in pod logs.

| Profile | admitted_total | duration_sec | offered_admit_rps | transient_errors |
|---------|----------------|-------------|-------------------|------------------|
| Persist **off** | 1,414,200 | 240.0 | **5892.50** | 1 |
| Persist **on** | 912,200 | 240.0 | **3800.83** | 2 |

- **Admission ratio (on/off):** `3800.83 / 5892.50` ≈ **64.5%**

## Completion summary (CloudWatch)

Source: `measurement_manifest.json`, `cw_metrics.json`; metric `AWS/SQS NumberOfMessagesDeleted` summed across `inspectio-v3-send-0..7`, period **60s**, stat **Sum**.

| Profile | combined_avg_rps | combined_peak_rps | active_periods | datapoints |
|---------|------------------|-------------------|----------------|------------|
| Persist **off** | **3367.14** | 5979.2 | 5 | 7 |
| Persist **on** | **2046.73** | 3334.5 | 5 | 6 |

- **Completion ratio R (on/off):** `2046.73 / 3367.14` × 100 ≈ **60.79%**
- **Gain vs WS3.1 baseline (44.84%):** `60.79 − 44.84` ≈ **+15.95 pp** (gate requires **+5.00 pp**)

## Hygiene validity

- `measurement_valid`: **true**
- `datapoint_count_difference`: **1** (≤ 1)
- `off_active_periods_gte_5`, `on_active_periods_gte_5`: **true**
- `period_is_60s`, `stat_is_sum`: **true**
- Job validity: off **succeeded=1, failed=0**; on **succeeded=1, failed=0**; single attempt each.
- Hygiene script **`decision`**: **PROMOTE** (threshold **52.66%** — **gate 1 only**; gate 2 checked manually below).

## Pipeline evidence (`writer_snapshot`)

- **Artifact:** `writer_snapshot_extract.json` (lines from `inspectio-persistence-writer*.log`).
- **Mode:** `pipeline_mode: "decoupled_v1"` present.
- **Under load:** e.g. shard-0 lines show `ack_queue_depth_high_water_mark` up to **510**, `ack_latency_ms_last` **2000** ms, non-zero `ingest_events_per_sec` during the on window — consistent with loaded persistence path (compare with iter-6 narrative in `iter-6/ITER6_RESULTS.md`).

## Decision gate evaluation

Per `P12_9_ITER6_TEST_EXECUTION_SPEC.md` / `P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md`:

1. Completion ratio **≥ 52.66%** → **PASS** (**~60.79%**)
2. Gain vs WS3.1 (**44.84%**) **≥ +5.00 pp** → **PASS** (**~+15.95 pp**)
3. Jobs + hygiene stability for this run → **PASS**
4. Pipeline evidence present → **PASS**

## Outcome

**PROMOTE** against the stated WS3 completion gates for this **iter-7** evidence bundle.

**Cluster state after run:** workloads on image `p12-9-deploy-20260402183410`; ConfigMap persist emit **true** after the on leg. For cost safety (optional), see spec Step 10 (`eksctl scale nodegroup`).

## Artifacts

- Timestamps: `off_start.txt`, `off_end.txt`, `on_start.txt`, `on_end.txt`
- Logs: `off-allpods.log`, `on-allpods.log`
- Jobs: `off_job_status.json`, `on_job_status.json`
- Hygiene: `sustain_summaries.json`, `cw_metrics.json`, `measurement_manifest.json`
- Snapshots: `deployments_snapshot.json`, `configmap_snapshot.json`, `writer_snapshot_extract.json`, writer shard `*.log`
