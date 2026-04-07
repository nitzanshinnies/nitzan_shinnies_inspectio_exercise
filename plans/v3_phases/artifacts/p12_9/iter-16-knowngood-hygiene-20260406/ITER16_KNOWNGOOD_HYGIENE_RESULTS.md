# P12.9 Iteration 16 — Known-good topology persist OFF vs ON (EKS, 2026-04-06)

## Topology (post-run snapshot)

- **api** 12, **expander** 16, **l1** 4, **worker-shard** 24×8, **persistence-writer-shard** 1×8, **persistence-writer** 0, **redis** 1 (`redis:7-alpine`)
- **Image (main pipeline):** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:eks-deploy-20260406115914`

## Procedure

- **Shape:** `v3_sustained_admit.py` **240s**, **120×200**, in-cluster `http://inspectio-l1:8080`
- **Persist OFF:** `INSPECTIO_V3_PERSIST_EMIT_ENABLED=false` → full stack recycle (all Deployments; redis image unchanged) → Job `inspectio-v3-p12-9-hygiene-off`
- **Persist ON:** `true` → full recycle → Job `inspectio-v3-p12-9-hygiene-on`
- **Hygiene:** `scripts/v3_p12_9_iter3_rerun_hygiene.py` `--preload-sec 60 --tail-sec 120` `--emit-metrics-exit-zero`

## Admission (driver)

| Leg | admitted_total | offered_admit_rps | transient_errors |
|-----|----------------|-------------------|------------------|
| Off | 1,501,600 | **6256.67** | 0 |
| On | 1,128,600 | **4702.50** | 1 |

## Completion (CloudWatch `NumberOfMessagesDeleted`, 8 send queues)

| Leg | combined_avg_rps | combined_peak_rps | datapoints | active_periods |
|-----|------------------|-------------------|------------|----------------|
| Off | **4199.65** | 6731.37 | 7 | 6 |
| On | **3056.16** | 4575.60 | 7 | 6 |

- **R (on/off):** **72.77%**
- **Gate 1 (R ≥ 52.66%):** **PASS** → hygiene **`decision: PROMOTE`**
- **Gate 2 ((R − 44.84) ≥ 5 pp):** **PASS**
- **`measurement_valid`:** **true** (`datapoint_count_difference`: **0**)

## Artifacts

`off_*` / `on_*` timestamps, job logs/JSON, `cw_metrics.json`, `sustain_summaries.json`, `measurement_manifest.json`, `deploy_snapshot.txt`, `configmap_snapshot.yaml` in this directory.
