# P12.9 Iteration 11 — Writer flush min batch 48 (EKS)

## Delta vs iter-10 baseline

- **Only change:** `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS` **64 → 48** (all else matches iter-10: ack **8**, `max_inflight` **10240**, flush interval **1800** ms, same image).
- **Image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-plan-a-perf-20260403040525`
- **Jobs:** `inspectio-v3-p12-9-iter11-flush48-off`, `inspectio-v3-p12-9-iter11-flush48-on`

## Admission (driver)

| Profile | admitted_total | offered_admit_rps | transient_errors |
|---------|----------------|-------------------|------------------|
| Off | 2,142,200 | **8925.83** | 1 |
| On | 1,048,800 | **4370.00** | 1 |

## Completion (CloudWatch)

Hygiene: `--preload-sec 60 --tail-sec 120` (spec defaults).

| Profile | combined_avg_rps | combined_peak_rps |
|---------|------------------|-------------------|
| Off | **5100.48** | 9302.92 |
| On | **2652.91** | 4389.42 |

- **R:** **52.01%** — **below** gate **52.66%**
- **`measurement_valid`:** **true** (`datapoint_count_difference`: 1)
- Hygiene **`decision`:** **NO-GO**
- **Gate 2** (vs 44.84%): **+7.17 pp** — still **≥ 5 pp** (manual check)

## Outcome

**NO-GO** on gate **1**. Smaller flush min batch **hurt** completion vs **iter-10** (~**55.95%** R at min batch **64**).

**Cluster:** `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS` **reverted to `64`** after this run; **`INSPECTIO_V3_PERSIST_EMIT_ENABLED`** left **`true`**.

## Next experiment (optional)

Done as **`iter-12-flush-min-batch-80`** — see `../iter-12-flush-min-batch-80/ITER12_FLUSH_MIN_BATCH_80_RESULTS.md`.

## Artifacts

Full bundle in this directory (`cw_metrics.json`, job logs, `writer_snapshot_extract.json`, etc.).
