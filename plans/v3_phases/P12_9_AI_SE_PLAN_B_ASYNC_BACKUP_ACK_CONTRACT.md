# Plan B — Async backup: transport ack contract (AI SE)

## Purpose

Align **implementation** with `P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md`: **S3 is backup**, **scheduler uses memory + SQS only**; **backup may lag** product-visible completion **without** being the **primary** throttle.

Today the writer **acks** persistence-transport messages **after** durable segment/checkpoint work (per `P12_DECISION_RECORD.md` **segment-before-checkpoint**). That preserves **strong handoff** but **couples** drain rate to **S3 + delete** latency. This plan defines **optional** relaxation paths.

## Preconditions

- Plan A sweeps **documented** in **`ITERn_RESULTS.md`** as insufficient for gates, **or** maintainer explicitly waives Plan A.
- Stakeholder agreement on **durability tier** (`best_effort` only vs new flag).
- Frozen benchmark artifacts (**`iter-6` or later**).

## Non-goals (initial slice)

- Breaking **segment-before-checkpoint** for **`strict`** mode without a **separate** code path and tests.
- Using S3 for runtime **due** scheduling.

## Design fork (one path per PR; do not mix without tests)

### Path B.1 — “Early ack” under `best_effort` only (highest risk)

**Idea:** **Delete** transport messages **before** S3 durably holds the segment+checkpoint (e.g. after **in-memory ingest** or after **enqueue to flush**), so the transport queue does not back up behind S3.

**Critical correction — redelivery vs loss:**

- After **successful early `DeleteMessage`**, SQS will **not** redeliver that message. If the process **crashes before** the data is durable in S3, that event’s backup may be **lost** (consistent with **`best_effort`** only if explicitly accepted).
- **Duplicate** events in backup come from **other** sources (re-publish, retries upstream), not from “SQS redelivery after early ack” for the same receipt handle.

**Risks:**

- **Lost backup** on crash between ack and S3.
- **Duplicate** persistence events from upstream must remain safe (**dedupe cap**, idempotent reducer).

**Required:**

- Explicit config, e.g. `INSPECTIO_V3_WRITER_TRANSPORT_ACK_TIMING=after_s3|after_ingest` (names illustrative).
- **Default `after_s3`** for backward compatibility.
- **Fault tests** and documented **acceptable loss** under `best_effort` for early-ack mode.

### Path B.2 — Keep ack-after-S3; remove other bottlenecks

**Idea:** Do not change ack ordering; **parallelize** safe phases of writer I/O, **tune S3 client**, or **add shards** (ops + cost).

**Required:**

- **No violation** of per-shard **segment-before-checkpoint** ordering.
- Benchmark + replay tests unchanged or extended.

### Path B.3 — Dual queue: “hot log” vs “cold backup”

**Idea:** Fast tier (stream / short-retention queue) + async S3 drain.

**Required:**

- Infra + security review; typically **out of scope** unless assigned.

## Task B.0 — Decision memo (mandatory before coding B.1)

Add to PR description or appendix:

- Chosen path (**B.1 / B.2 / B.3**).
- **Failure modes** accepted under `best_effort` (especially **loss window** for B.1).
- **Metrics** that prove improvement: **R**, **`backup_lag`**, transport **visible** depth, DLQ.

## Task B.1-impl — Implementation checklist (when Path **B.1** chosen)

1. Settings + validation; wire **`persistence_writer/main.py`** ack points.
2. Document interaction with **`writer_dedupe_event_id_cap`** under duplicate ingress.
3. **Unit tests:** ack vs mocked S3 call order for both modes.
4. **Integration:** `tests/integration/test_v3_persistence_writer_fake_flow.py` for both modes.
5. **EKS:** full A/B per Plan D; compare **R**, S3 object growth, DLQ, writer snapshots.

## Task B.2-impl — Implementation checklist (when Path **B.2** chosen)

1. Profile writer (I/O wait vs CPU).
2. Minimal safe concurrency change; preserve shard ordering.
3. Tests + benchmark as above.

## Rollback

- Feature flag / config → **`after_s3`**.
- Image + ConfigMap rollback per `P12_9_ITER6_TEST_EXECUTION_SPEC.md` Step 9 pattern.

## References

- `plans/v3_phases/P12_DECISION_RECORD.md`
- `plans/v3_phases/P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md`
- `src/inspectio/v3/persistence_writer/writer.py`
- `src/inspectio/v3/persistence_writer/main.py`
