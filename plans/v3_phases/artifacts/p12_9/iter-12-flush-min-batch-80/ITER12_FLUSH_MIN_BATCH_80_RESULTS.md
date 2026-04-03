# P12.9 Iteration 12 — Writer flush min batch 80 (EKS)

## Delta vs iter-10 baseline

- **Only change:** `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS` **64 → 80** (ack delete **8**, `INSPECTIO_V3_PERSIST_TRANSPORT_MAX_INFLIGHT` **10240**, flush interval **1800** ms unchanged; same image as iter-10/11).
- **Image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-plan-a-perf-20260403040525`
- **Jobs:** `inspectio-v3-p12-9-iter12-flush80-off`, `inspectio-v3-p12-9-iter12-flush80-on` (240s, 120×200, `python scripts/v3_sustained_admit.py`, `serviceAccountName: inspectio-app`, `imagePullPolicy: Always`).

### Execution note

An initial Job used a non-existent Python module path (`inspectio.scripts.v3_p12_9_plan_a_load_test`); that Job was deleted. The successful runs match **`P12_9_ITER6_TEST_EXECUTION_SPEC.md`**: `python scripts/v3_sustained_admit.py` with `--api-base http://inspectio-l1:8080`.

### Measurement windows

`off_start.txt` / `off_end.txt` and `on_*` were derived **post hoc** from Kubernetes Job **`status.startTime`** / **`status.completionTime`** (RFC3339 → `Z`), not from wall-clock `date` immediately before/after `kubectl apply` as in the spec. The hygiene script’s preload/tail windows still use **60s / 120s**.

## Admission (driver)

| Profile | admitted_total | offered_admit_rps | transient_errors |
|---------|----------------|-------------------|------------------|
| Off | 2,008,200 | **8367.50** | 1 |
| On | 1,030,400 | **4293.33** | 3 |

## Completion (CloudWatch) — canonical hygiene

Hygiene: `scripts/v3_p12_9_iter3_rerun_hygiene.py` with **`--preload-sec 60 --tail-sec 120`**.

| Profile | combined_avg_rps | combined_peak_rps | datapoints | active_periods |
|---------|------------------|-------------------|------------|----------------|
| Off | **4781.43** | 8540.33 | 7 | 5 |
| On | **2824.01** | 4250.1 | 6 | 5 |

- **R** (completion ratio %): **59.06%** (`cw_metrics.json`)
- **Gain vs 44.84% baseline:** **+14.22 pp**
- **`measurement_valid`:** **true** (`datapoint_count_difference`: **1**)
- Hygiene **`decision`:** **PROMOTE**

## Gates

1. **R ≥ 52.66%** → **PASS** (~59.06%)
2. **(R − 44.84) ≥ 5 pp** → **PASS** (~+14.22 pp)
3. Jobs + hygiene → **PASS**

## Compare to iter-10 and iter-11

| Run | flush min batch | R % | Notes |
|-----|-----------------|-----|--------|
| iter-10 | 64 | **55.95** | `max_inflight` 10240 |
| iter-11 | 48 | **52.01** | NO-GO; reverted to 64 |
| iter-12 | **80** | **59.06** | **+~3.1 pp** vs iter-10 R (same gates); admit-side RPS differs run-to-run (variance) |

## Outcome

**PROMOTE** on stated gates for **iter-12**. Repo **`deploy/kubernetes/configmap.yaml`** updated to **`80`**; live cluster left at **80** with **`INSPECTIO_V3_PERSIST_EMIT_ENABLED`** **`true`** after the on-leg recycle.

## Artifacts

This directory: timestamps, job logs/JSON, `sustain_summaries.json`, `cw_metrics.json`, `measurement_manifest.json`, CM/deploy snapshots.
