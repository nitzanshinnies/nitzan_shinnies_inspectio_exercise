# P0 — Package, schemas, retry math, assignment stubs

**Goal:** **`inspectio.v3`** skeleton, **Pydantic** queue envelopes, pure **retry deadlines** (master plan **4.7**), PDF-shaped **stubs** (**4.6**). No HTTP, SQS, or Redis.

**Refs:** master plan **4.4**, **4.6**, **4.7**; **`plans/ASSIGNMENT.pdf`** (do not change signatures; adapters OK).

## Done when

- [ ] Package **`src/inspectio/v3/`** (or equivalent agreed path) used consistently in later phases.
- [ ] **`BulkIntentV1`** / **`SendUnitV1`** with **`schemaVersion`**, **`traceId`**, **`batchCorrelationId`** where applicable; fields per **4.4** (`receivedAtMs` from L2; **`attemptsCompleted`** = **0** before first **`try_send`** on the unit).
- [ ] **`assignment_surface`**: **`Message`**, internal **`try_send(Message) -> bool`** (scheduler in P4 branches on this); optional void wrapper that still delegates **`bool`** internally; stubs **`NotImplementedError`** unless a test needs a fake.
- [ ] **`retry_schedule`**: offsets **`(0, 500, 2000, 4000, 8000, 16000)`** ms from **`receivedAtMs`** for attempts **#1–#6** (**4.7**); pure functions + **unit** tests (fake clock / table-driven).
- [ ] **`pytest -m unit`** green; **`v2_obsolete`** excluded from collection; no legacy imports (master **6**, item **7**).

## Layout (suggested)

`v3/schemas/` (bulk + send unit), `v3/domain/retry_schedule.py`, `v3/assignment_surface.py`.

## Tests

| Marker | Cover |
|--------|--------|
| unit | Schema JSON round-trip; invalid `count`; all six deadline values; imports |

## Out of scope

FastAPI, SQS, L1. **S3 / AC5** remains deferred (master plan out-of-scope list, **AC5**).

**Next:** P1 builds **`BulkIntentV1`** in L2 and enqueues via a protocol.
