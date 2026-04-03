# P12.9 Iteration 8 — Plan A integration EKS benchmark

## Candidate image and branch

- **Image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-plan-a-perf-20260403040525`
- **Branch:** `feat/p12-9-plan-a-eks-perf` @ **`18480a6`** at image build time (Plan A integration merges through A.2); artifact bundle committed as **`73c54a8`** on the same branch.
- **Jobs:** `inspectio-v3-p12-9-iter8-plan-a-off`, `inspectio-v3-p12-9-iter8-plan-a-on` (240s sustain, 120×200, in-cluster L1).
- **Job pod:** `serviceAccountName: inspectio-app`, `imagePullPolicy: Always`, same `IMG` as all app Deployments.

## Config under test (live cluster patch + recycle)

Applied via `kubectl patch configmap inspectio-v3-config` before the off leg (with `INSPECTIO_V3_PERSIST_EMIT_ENABLED=false`), full stack rollout restart:

- `INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY=6`
- `INSPECTIO_V3_WRITER_PIPELINE_ENABLE=true`
- `INSPECTIO_V3_WRITER_RECEIVE_LOOP_PARALLELISM=2`
- `INSPECTIO_V3_WRITER_FLUSH_LOOP_SLEEP_MS=10`
- `INSPECTIO_V3_PERSIST_TRANSPORT_MAX_INFLIGHT=8192`
- `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_INTERVAL_MS=1800`

On leg: `INSPECTIO_V3_PERSIST_EMIT_ENABLED=true` + full recycle. See `configmap_snapshot.json` (captured before writer log pull; may reflect post-on state).

## Admission summary (driver)

| Profile | admitted_total | duration_sec | offered_admit_rps | transient_errors |
|---------|----------------|-------------|-------------------|------------------|
| Persist **off** | 2,141,000 | 240.0 | **8920.83** | 2 |
| Persist **on** | 1,081,400 | 240.0 | **4505.83** | 5 |

- **Admission ratio (on/off):** ≈ **50.5%**

## Completion summary (CloudWatch)

Metric `AWS/SQS NumberOfMessagesDeleted`, **Sum**, **60s**, summed over `inspectio-v3-send-0..7`.

| Profile | combined_avg_rps | combined_peak_rps | active_periods | datapoints |
|---------|------------------|-------------------|----------------|------------|
| Persist **off** | **5097.62** | 9046.53 | 5 | 7 |
| Persist **on** | **2613.50** | 4431.93 | 6 | 7 |

- **Completion ratio R (on/off × 100):** **51.27%** (`cw_metrics.json`: `completion_ratio_percent_on_over_off`)
- **Gain vs WS3.1 baseline (44.84%):** **+6.43 pp** (gate 2 requires **+5.00 pp**)

## Hygiene validity

- `measurement_valid`: **true**
- `datapoint_count_difference`: **0**
- Jobs: off/on **succeeded=1**, **failed=0**
- Hygiene script **`decision`**: **NO-GO** (threshold **52.66%** — **gate 1 only**)

## Gate evaluation (full)

1. **R ≥ 52.66%** → **FAIL** (**51.27%**)
2. **(R − 44.84) ≥ 5.00 pp** → **PASS** (**+6.43 pp**)
3. Jobs + hygiene → **PASS**
4. `writer_snapshot` evidence → **PASS** (`writer_snapshot_extract.json`, `pipeline_mode: decoupled_v1`; under load e.g. `ack_queue_depth_high_water_mark` ~520, `ack_latency_ms_max` ~1.6s on shard-0 samples)

## Outcome

**NO-GO** on **gate 1** despite Plan A tuning bundle. Compared to **iter-7** (`ITER7_RESULTS.md`), this run shows higher absolute completion RPS (different window/cluster conditions) but a **lower** on/off completion ratio.

**Follow-up:** **`iter-9-ack8`** raised **`INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY`** to **8** only; **R ≈ 53.35%** → **PROMOTE** on both gates (see `../iter-9-ack8/ITER9_ACK8_RESULTS.md`).

## Artifacts

Timestamps, logs, job JSON, hygiene outputs, writer logs, and snapshots are in this directory (`iter-8-plan-a-perf/`).
