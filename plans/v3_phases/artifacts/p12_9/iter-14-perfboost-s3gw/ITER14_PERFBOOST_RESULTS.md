# P12.9 Iteration 14 — Post perf boost (S3 gateway + `p12-9-perfboost` image)

## Delta vs prior runs

- **Infra:** **S3 VPC gateway endpoint** **`vpce-08ff97d249c7fad7b`** on cluster VPC (see **`P12_9_EKS_S3_NETWORK_PATH.md`**).
- **Image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-perfboost-20260404091726` (includes **`GET /internal/persistence-transport-metrics`** when **`INSPECTIO_V3_EXPOSE_PERSISTENCE_TRANSPORT_METRICS=true`**).
- **Config:** Same promoted Plan A as **iter-12** (`flush_min` **80**, `max_inflight` **10240**, ack **8** per live CM); **`INSPECTIO_V3_EXPOSE_PERSISTENCE_TRANSPORT_METRICS`** **true** on cluster.
- **Jobs:** `inspectio-v3-p12-9-iter14-perfboost-off`, `inspectio-v3-p12-9-iter14-perfboost-on` (240s, 120×200, `scripts/v3_sustained_admit.py`, `serviceAccountName: inspectio-app`, `imagePullPolicy: Always`).
- **Procedure:** Full stack recycle before run; **persist off** → recycle → off job; **persist on** → recycle → on job; wall-clock **`off_*` / `on_*`** timestamps per **`P12_9_ITER6_TEST_EXECUTION_SPEC.md`**.

## Admission (driver)

| Profile | admitted_total | offered_admit_rps | transient_errors |
|---------|----------------|-------------------|------------------|
| Off | 1,706,400 | **7110.00** | 0 |
| On | 921,800 | **3840.83** | 5 |

**Note:** Persist-on **admit RPS** is **much lower** than off in this window (~**54%** of off by admit), so completion **R** is not comparable to runs where on/off admit was closer (e.g. **iter-13**).

## Completion (CloudWatch)

Hygiene: `scripts/v3_p12_9_iter3_rerun_hygiene.py` **`--preload-sec 60 --tail-sec 120`**.

| Profile | combined_avg_rps | combined_peak_rps | datapoints | active_periods |
|---------|------------------|-------------------|------------|----------------|
| Off | **4062.86** | 7137.43 | 7 | 5 |
| On | **2031.87** | 3786.93 | 7 | 6 |

- **R:** **50.01%**
- **Gate 1 (R ≥ 52.66%):** **FAIL** — hygiene **`decision: NO-GO`**
- **Gate 2 ((R − 44.84) ≥ 5 pp):** **PASS** (~**+5.17 pp**)
- **`measurement_valid`:** **true** (`datapoint_count_difference`: **0**)

## Interpretation

This **`iter-N`** does **not** demonstrate a completion-ratio **gain** vs the **52.66%** promotion gate. The persist-on leg shows **strong admit-side depression** relative to off, so **R** is dominated by **uneven load envelope**, not a clean read on “S3 endpoint alone.”

**Suggested follow-ups:** (1) Re-run once with stable off/on admit (watch **`SUSTAIN_SUMMARY`** parity). (2) Sample **`/internal/persistence-transport-metrics`** during on-leg load for **`dropped_backpressure` / `publish_failures`**. (3) Compare **`writer_snapshot`** peaks to **iter-13**.

## Artifacts

This directory: job logs/JSON, `sustain_summaries.json`, `cw_metrics.json`, `measurement_manifest.json`, CM/deploy snapshots.
