# P12.9 — Observability runbook (completion vs backup path)

## Purpose

Triage **low completion RPS** (gate metric) vs **healthy admission** vs **persistence backup pressure** using logs, SQS attributes, CloudWatch, and **`writer_snapshot`** lines. Aligned with **`P12_9_AI_SE_PLAN_C_OBSERVABILITY.md`** and **`P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md`**.

## Primary gate inputs

- **Completion RPS (off/on ratio):** sum **`AWS/SQS` → `NumberOfMessagesDeleted`**, **Sum**, **60s** period, over **`inspectio-v3-send-0` … `inspectio-v3-send-{K-1}`** for the sustain window — same construction as **`scripts/v3_p12_9_iter3_rerun_hygiene.py`**.
- **Hygiene validity:** **`measurement_valid: true`**, job **`succeeded=1`**, **`failed=0`** per leg; manual **gate 2**: **(R − 44.84) ≥ 5** pp (see **`P12_9_AI_SE_HANDOFF_INDEX.md`**).
- **Admit RPS:** driver JSON in Job logs (`SUSTAIN_SUMMARY` / sustained admit script output) — **diagnostic**, not the completion gate.

## Decision tree (symptom → likely layer)

| Observation | Likely focus | Next checks |
|-------------|----------------|-------------|
| **Completion RPS low** and **send-queue `ApproximateNumberOfMessagesVisible` ≈ 0** (per shard during load) | **Upstream of send consumption** — expander, worker receive/publish, L2, or bulk path | Worker / expander logs for **`send_ok`** / errors; bulk queue depth; L2 5xx; scale worker or expander knobs per **`P12_9_AI_SE_PLAN_A`** (not persistence-first). |
| **Persist-transport queue visible high** (shard queues backing the writer) | **Backup path** — writer ingest, flush, S3, **ack delete** | **`writer_snapshot`**: **`ack_queue_depth_*`**, **`ack_latency_ms_max`**; **`INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY`**; S3 error counters in snapshot; **`flush_failures`**. |
| **Admit RPS low** but **completion / deletes healthy** | **L1/L2 admission** or driver limits | L1→L2 timeouts, **`INSPECTIO_L1_L2_*`**, connection limits; driver **`--concurrency`** / **`--batch`**. |
| **Admit healthy**, **send visible high**, **completion low** | **Worker send throughput** or **expander fan-out** | Per-shard worker replicas; **`INSPECTIO_V3_EXPANDER_*`**; send queue not-visible (in flight) vs visible. |

## `writer_snapshot` (persistence writer logs)

- **`pipeline_mode`:** expect **`decoupled_v1`** when decoupled pipeline is enabled.
- **Ack pressure:** **`ack_queue_depth_high_water_mark`**, **`ack_latency_ms_max`** — correlate with SQS **`DeleteMessageBatch`** concurrency (**`INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY`**).
- **Flush / S3:** **`flush_batches`**, **`flush_failures`**, **`s3_errors`**; optional timing fields when the image includes writer instrumentation (see **`P12_9_TIMING_FINDINGS_AND_AI_SE_PERSISTENCE_PERF_PLAN.md`**).

## Quick commands (examples)

```bash
# Replace URL and region; repeat per send queue and per persist-transport queue.
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessagesVisible ApproximateNumberOfMessagesNotVisible \
  --region us-east-1
```

```bash
kubectl -n inspectio logs deployment/inspectio-persistence-writer-shard-0 --tail=200 | rg writer_snapshot
```

## References

- **`plans/v3_phases/P12_9_AI_SE_PLAN_C_OBSERVABILITY.md`** — metrics map and task list.
- **`plans/v3_phases/P12_9_AI_SE_HANDOFF_INDEX.md`** — canonical benchmark shape and gates.
- **`scripts/v3_p12_9_iter3_rerun_hygiene.py`** — hygiene JSON and **`decision`** (gate 1 only).
