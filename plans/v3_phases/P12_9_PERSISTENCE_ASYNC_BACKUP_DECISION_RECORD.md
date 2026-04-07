# P12.9 — Persistence as pure async backup (decision record)

## Status

**Locked:** 2026-04-02. **Priority:** recover **throughput** under persist-on load first; **tighten durability** only in controlled steps that do not recreate the same coupling.

This record is the **product and architecture intent** for v3 persistence. It **supplements** branch-local locks such as `P12_DECISION_RECORD.md` (segment-before-checkpoint, transport ordering) by stating **what S3 is for** in the running system.

---

## Problem

The pipeline **emit → persistence transport → writer → S3 → transport ack/delete** was easy to treat as a **strong durability handoff**: progress on the backup path shows up as **lag, ack-queue depth, and completion RPS loss** versus persist-off. That blurs two roles:

1. **Live control plane** — who may send, retry, and complete work (scheduler + queues).
2. **Durable history** — what we can reconstruct after failure or audit.

Coupling (2) too tightly to (1) makes S3 **feel** like part of the hot path even when the **scheduler** never reads S3.

---

## Decision

### 1) Classification: S3 is backup, not the runtime SoT

**Persistence materialized in S3 (segments, checkpoints, related objects) is *pure asynchronous backup*** of events/facts the system has already accepted for processing elsewhere.

- It is **not** the source of truth for **steady-state scheduling** (due retries, eligibility, completion of send-queue work).
- It **is** the basis for **recovery replay**, audit, and “what happened” reconstruction when primary state is rebuilt.

### 2) Scheduler and runtime SoT: memory + SQS only

- The **send scheduler** and analogous runtime loops use **in-memory structures** and **SQS** (receipt handles, visibility, per-queue consumption) to decide **what runs next** and **when a unit of work is finished** from the product’s perspective.
- **No S3 list/prefix scans** (or per-tick S3 reads) for **due** work. (Bootstrap/recovery may **hydrate** memory from replay; that is **not** the hot path.)

### 3) Duplication, ordering, and replay

Backup ingress may **duplicate** or **reorder** events. **Recovery** must use **deterministic replay order** and an **idempotent reducer** (per `messageId`, monotonic `attemptCount`, **terminal finality**, stable tie-breakers) so multiple stored facts collapse to one logical outcome.

Temporary overlap in stored facts (“pending” vs “done”) is acceptable **if** every consumer applies the same reduction rules.

### 4) Phased delivery: performance first, then durability

1. **Performance phase:** Change implementation and tuning so **persist-on throughput** approaches gates (admit + **completion** as measured by the hygiene benchmarks), without weakening **scheduler correctness** (still memory + queues).
2. **Durability phase:** Incrementally add **stricter** guarantees (e.g. optional `strict` handoff, stronger observability, compaction/GC) **only** where benchmarks and failure-injection prove the cost is acceptable.

---

## Non-goals (for this decision)

- Requiring **synchronous S3** on API or worker **admit / try_send** hot paths.
- Using **S3 as an index** for runtime due scheduling.

---

## Relationship to existing P12 locks

Where `plans/v3_phases/P12_DECISION_RECORD.md` exists, it remains the reference for **writer internal contracts** (e.g. segment-before-checkpoint, bounded handoff buffers). This P12.9 record does **not** delete those contracts; it **reframes intent**:

- Writer behavior should be optimized so **backup** can **lag** without being the **primary throttle** on **send-queue completion** and **user-visible throughput**, within the active durability mode (`best_effort` today).

---

## Follow-up work (separate PRs; not part of this document-only change)

- **Ack semantics:** Align transport **delete/ack** with “**accepted for backup**” vs “**durable in S3**” explicitly, or scale ack concurrency / pipeline stages so S3 is not the implicit barrier to draining transport.
- **Metrics:** Distinguish **backup_lag**, **backup_drops** (best_effort), from **completion RPS** (e.g. send-queue deletes).
- **Config:** Any future **`strict`** mode must be **opt-in** and benchmark-gated.

---

## Review cadence

Revisit this record when:

- Persist-on **completion ratio** meets agreed promotion gates, or
- Introducing **`strict`** durability or changing **ack** contracts.
