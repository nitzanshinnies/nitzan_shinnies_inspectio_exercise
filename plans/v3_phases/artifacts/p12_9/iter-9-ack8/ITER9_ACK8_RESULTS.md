# P12.9 Iteration 9 — Ack delete concurrency 8 (EKS)

## Change vs iter-8

- **Only delta:** `INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY` **6 → 8** on the live cluster (same image and other Plan A keys as **iter-8-plan-a-perf**).
- **Image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-plan-a-perf-20260403040525`
- **Jobs:** `inspectio-v3-p12-9-iter9-ack8-off`, `inspectio-v3-p12-9-iter9-ack8-on` (240s, 120×200, `serviceAccountName: inspectio-app`, `imagePullPolicy: Always`).

## Admission (driver)

| Profile | admitted_total | offered_admit_rps | transient_errors |
|---------|----------------|-------------------|------------------|
| Off | 2,136,800 | **8903.33** | 0 |
| On | 1,122,200 | **4675.83** | 1 |

- Admit on/off ≈ **52.5%**

## Completion (CloudWatch)

| Profile | combined_avg_rps | combined_peak_rps |
|---------|------------------|-------------------|
| Off | **5087.62** | 9030.97 |
| On | **2714.25** | 4504.98 |

- **R** (completion ratio %): **53.35%** (`cw_metrics.json`)
- **Gain vs 44.84% baseline:** **+8.51 pp**

## Gates

1. **R ≥ 52.66%** → **PASS** (53.35%)
2. **(R − 44.84) ≥ 5 pp** → **PASS** (+8.51 pp)
3. `measurement_valid`: **true**; jobs **succeeded=1**, **failed=0** each leg.
4. Hygiene script **`decision`**: **PROMOTE** (gate 1 only — gate 2 confirmed manually above).

## Writer evidence

- **`writer_snapshot_extract.json`**: `pipeline_mode: decoupled_v1`; under load shard-0 samples show **`ack_latency_ms_max`** up to **~1.85s** (vs **~1.6s** at ack=6 in iter-8) with similar **`ack_queue_depth_high_water_mark`** ~530 — still healthy enough for gate pass.

## Outcome

**PROMOTE** on WS3 completion gates for this run. Confirms **iter-8** was **ack-bound** at concurrency **6**; **8** clears both gates with the same code image.

## Compare to iter-8-plan-a-perf

| Run | Ack CM | R % | Hygiene decision |
|-----|--------|-----|------------------|
| iter-8 | 6 | 51.27 | NO-GO |
| iter-9 | 8 | 53.35 | PROMOTE |

Artifacts in this folder; repo template and `settings.py` default updated to **8** in the branch that commits this bundle.

**Follow-up:** **`iter-10-maxinflight-10240`** raised **`INSPECTIO_V3_PERSIST_TRANSPORT_MAX_INFLIGHT`** to **10240** only; **R ≈ 55.95%** (hygiene-valid) — see `../iter-10-maxinflight-10240/ITER10_MAXINFLIGHT_RESULTS.md`.
