# P12.9 Iteration 15 — Persist OFF vs ON (EKS, 2026-04-06)

## Procedure

- **Image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:eks-deploy-20260406115914`
- **Shape:** `v3_sustained_admit.py` **240s**, **120×200**, in-cluster `http://inspectio-l1:8080`
- **Persist OFF:** `INSPECTIO_V3_PERSIST_EMIT_ENABLED=false` → full stack recycle (all Deployments except unchanged redis image) → Job `inspectio-v3-p12-9-persist-off`
- **Persist ON:** `true` → full recycle → Job `inspectio-v3-p12-9-persist-on`
- **Hygiene:** `scripts/v3_p12_9_iter3_rerun_hygiene.py` `--preload-sec 60 --tail-sec 120` `--emit-metrics-exit-zero`

## Admission (driver)

| Leg | admitted_total | offered_admit_rps | transient_errors |
|-----|----------------|-------------------|------------------|
| Off | 981,000 | **4087.50** | 6 |
| On | 635,000 | **2645.83** | 4 |

## Completion (CloudWatch `NumberOfMessagesDeleted`, 8 send queues)

| Leg | combined_avg_rps | combined_peak_rps | datapoints | active_periods |
|-----|------------------|-------------------|------------|----------------|
| Off | **2509.51** | 4052.78 | 7 | 6 |
| On | **1847.16** | 2654.95 | 6 | 6 |

- **R (on/off):** **73.61%**
- **Gate 1 (R ≥ 52.66%):** **PASS** → hygiene **`decision: PROMOTE`**
- **Gate 2 ((R − 44.84) ≥ 5 pp):** **PASS**
- **`measurement_valid`:** **true** (`datapoint_count_difference`: **1**)

## Artifacts

`off_*` / `on_*` timestamps, job logs/JSON, `cw_metrics.json`, `sustain_summaries.json`, `measurement_manifest.json`, CM/deploy snapshots in this directory.
