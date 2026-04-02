# Plan C — Observability for backup vs completion (AI SE)

## Purpose

Give SEs and operators **separable signals**:

1. **Product throughput** — send-queue completion (gate metric), L2 admit (driver).
2. **Backup health** — persistence transport depth, writer flush/ack, S3 errors, **backup lag**.

Aligned with `P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md`.

## Preconditions

- Writer **`decoupled_v1`** deployed (`writer_snapshot` contains `pipeline_mode`).
- **CloudWatch** + **SQS** API access (same account as queues).
- Pod **logs** accessible (`kubectl logs` minimum).

## Canonical metrics map (baseline — extend in PR if code adds counters)

| Concern | What to query | Source / command | Gate or triage |
|---------|----------------|------------------|----------------|
| **Completion ratio inputs** | `NumberOfMessagesDeleted`, **Sum**, **60s**, queues **`inspectio-v3-send-0`…`7`** | Hygiene script + CW | **Primary gate** (with off/on windows) |
| **Admit RPS** | `SUSTAIN_SUMMARY` in Job logs | `off-allpods.log` / `on-allpods.log` | Driver-side; not the completion gate |
| **Send queue backlog** | `ApproximateNumberOfMessagesVisible`, `ApproximateNumberOfMessagesNotVisible` | `aws sqs get-queue-attributes` or CW | High visible → workers/expander/L2 pressure |
| **Persist transport backlog** | Same attributes per **`inspectio-v3-persist-transport-0`…`** | AWS CLI / CW | High visible → backup path not draining |
| **Writer ack pressure** | `ack_queue_depth_current`, `ack_queue_depth_high_water_mark`, `ack_latency_ms_max` | `rg writer_snapshot` / `grep writer_snapshot` on shard logs | Correlates with delete concurrency tuning |
| **Writer ingest vs flush** | `ingest_events_per_sec`, `receive_events_total`, `flush_batches`, `flush_failures`, `s3_errors` | `writer_snapshot` JSON | Distinguish “receiving” vs “S3 failing” |
| **Pipeline mode** | `pipeline_mode` | `writer_snapshot` | Must show expected mode (`decoupled_v1`) |
| **Emitter drops (best_effort)** | If present: counters or logs on reject | `persistence_emitter` / transport producer | If absent, Task C.2 adds |

## Task C.1 — Keep this table authoritative

When adding metrics in code, **update this table** in the same PR (no orphan counters).

## Task C.2 — Code: explicit counters (if audit finds gaps)

**Inspect:**

- `src/inspectio/v3/persistence_emitter/transport.py`
- `src/inspectio/v3/persistence_writer/metrics.py`
- `src/inspectio/v3/worker/metrics.py` (if present)

**Deliverables (as needed):**

1. Counter or rate-limited log: **`persist_emit_rejected_total`** / **`persistence_backup_drop_total`** on `best_effort` drop.
2. Ensure **`transport_oldest_age_ms_max`** (or equivalent) appears in **`writer_snapshot`** per shard; extraction script documents field.

**Tests:** unit tests cover increment on simulated full buffer / drop.

## Task C.3 — Script: one-shot lag report

- **Prefer extending** `scripts/v3_p12_9_lag_phase_analyze.py` if it exists on your branch.
- **Input:** `--region`, queue URL list or name prefix, optional profile.
- **Output:** JSON: visible / not-visible / delayed per queue; optional CW stat for last hour.

## Task C.4 — Runbook for SE triage

**Do not** edit only under `artifacts/` (generated evidence). Add **`plans/v3_phases/P12_9_OBSERVABILITY_RUNBOOK.md`** with:

- If **completion RPS** low and **send visible ≈ 0** → **worker / L2 / expander** path; persistence may not be the limiter.
- If **persist-transport visible** high → **writer** ack depth, **S3 errors**, **ack delete concurrency**.
- If **admit** low but **completion** healthy → **L1/L2** admission vs downstream mismatch.

The index **`P12_9_AI_SE_HANDOFF_INDEX.md`** already reserves **`P12_9_OBSERVABILITY_RUNBOOK.md`** under **Runbooks**; no further index edit required once the file exists.

## Definition of done

- This plan’s **metrics map** reflects reality after any code change.
- **Either** new observable (counter/script) **or** written audit “no gap” in **`ITERn_RESULTS.md`** / PR description.
- **`plans/v3_phases/P12_9_OBSERVABILITY_RUNBOOK.md`** exists with the triage bullets above.

## Non-goals

- Installing Prometheus/Grafana stack unless repo standard already mandates it.
