# P12.9 Iteration 13 — Architect Phase C/D evidence (EKS)

## Intent

Execute **`ARCHITECT_PLAN_PERSISTENCE_AND_PLATFORM.md` §9** next actions:

- **Phase D:** Static network path checklist → **`../../P12_9_EKS_S3_NETWORK_PATH.md`**
- **Phase C:** Assess **persistence transport producer** vs completion ratio under promoted ConfigMap (same image as **iter-12**).
- **Phase A (skew):** Post-run **`writer_snapshot`** per writer deploy → **`shard_skew_summary.json`**

## Config / image

- **Image:** `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-plan-a-perf-20260403040525`
- **ConfigMap (unchanged vs iter-12):** `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS` **80**, `INSPECTIO_V3_PERSIST_TRANSPORT_MAX_INFLIGHT` **10240**, ack delete **8**, persist **on** for on-leg.
- **Jobs:** `inspectio-v3-p12-9-iter13-phasecd-off`, `inspectio-v3-p12-9-iter13-phasecd-on`
- **Windows:** **`off_start.txt` / `off_end.txt` / `on_start.txt` / `on_end.txt`** from **wall-clock `date -u`** immediately before/after job apply/wait (**`P12_9_ITER6_TEST_EXECUTION_SPEC.md`** style).

## Admission (driver)

| Profile | admitted_total | offered_admit_rps | transient_errors |
|---------|----------------|-------------------|------------------|
| Off | 2,203,800 | **9182.50** | **2169** |
| On | 1,721,800 | **7174.17** | 13 |

**Note:** The **off** leg reported **large** `transient_errors` (driver-side); jobs still **`succeeded=1`**. Treat admit-side stress as a **variance / saturation** signal; completion hygiene below remained **`measurement_valid: true`**.

## Completion (CloudWatch)

Hygiene: `scripts/v3_p12_9_iter3_rerun_hygiene.py` **`--preload-sec 60 --tail-sec 120`**.

| Profile | combined_avg_rps | combined_peak_rps | datapoints | active_periods |
|---------|------------------|-------------------|------------|----------------|
| Off | **5041.89** | 7501.55 | 7 | 6 |
| On | **3350.02** | 4884.12 | 7 | 7 |

- **R:** **66.44%**
- **Gate 2:** **(R − 44.84) ≈ +21.6 pp** — **PASS**
- **`measurement_valid`:** **true** (`datapoint_count_difference`: **0**)
- Hygiene **`decision`:** **PROMOTE**

## Phase C — Producer / `await emit` throttle

**`PersistenceTransportMetrics`** (`published_ok`, `dropped_backpressure`, `publish_failures`, publish duration aggregates) live **in-process** on **`SqsPersistenceTransportProducer`** and are **not** exposed on **`/healthz`** in the current L2 surface.

**This run did not add new instrumentation.** Therefore Phase C **cannot** be closed as “publish path ruled in/out **with producer metric numbers**” without a **Plan C** emission (logs, metrics endpoint, or sidecar scrape).

**Interpretation vs R:** **R ≈ 66%** is **high** in this window (higher than **iter-12 ~59%**), consistent with **variance** and different admit/error envelope — **not** a proof that producer backpressure is absent. **Recommendation:** add a **low-rate structured log** or **debug snapshot** of `producer.metrics` on L2/API pods during load, then re-run one **`iter-N`**.

## Phase A — Shard skew (post-on window snapshots)

Source: last **`writer_snapshot`** line per **`inspectio-persistence-writer-shard-{0..7}`** after the on leg → **`shard_skew_summary.json`**.

| logical `shard` | `receive_events_total` | `ingest_events_per_sec` | `ack_latency_ms_max` |
|-----------------|------------------------|---------------------------|----------------------|
| 0 | 117,972 | 309.7 | 2255 |
| 1 | 107,367 | 286.7 | 2281 |
| 2 | 109,704 | 287.5 | 2233 |
| 3 | 110,986 | 294.3 | 2134 |
| 4 | 110,492 | 293.3 | 2880 |
| 5 | 108,583 | 292.4 | 1962 |
| 6 | **94,152** | **253.0** | 2886 |
| 7 | 106,373 | 286.7 | 2286 |

**Conclusion:** **Mild skew** — **shard 6** ~**20%** below the highest `receive_events_total` (**shard 0**), not an order-of-magnitude “one writer hot, others idle” pattern. Hypothesis **not** “extreme concentration”; still worth revisiting after routing changes or different load mixes.

## Artifacts

- `cw_metrics.json`, `measurement_manifest.json`, `sustain_summaries.json`, job logs/JSON, CM/deploy snapshots
- `writer_shard_*_last_snapshot.log`, `shard_skew_summary.json`
- Phase D: **`plans/v3_phases/P12_9_EKS_S3_NETWORK_PATH.md`**
