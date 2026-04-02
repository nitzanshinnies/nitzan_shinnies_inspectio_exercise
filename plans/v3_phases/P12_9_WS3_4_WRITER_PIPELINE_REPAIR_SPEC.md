# P12.9 WS3.4 Writer Pipeline Repair - Strict Implementation Spec

## Purpose

Define a non-negotiable implementation contract to repair persistence writer throughput by removing per-shard writer loop serialization while preserving durability and replay invariants.

This spec is written for AI implementation and is intentionally prescriptive.
Deviations are not allowed unless explicitly approved in writing.

SE command runbook:

- `plans/v3_phases/artifacts/p12_9/iter-6/ITER6_SE_HANDOFF_BRIEF.md`
- Execution spec (authoritative test protocol):
  `plans/v3_phases/P12_9_ITER6_TEST_EXECUTION_SPEC.md`

---

## Why this is required

Current architecture is correctness-safe but throughput-limited by a serial per-shard writer loop:

1. `receive_many -> ingest -> flush_due -> ack_many` executes in one loop.
2. Flush and ack I/O block new receives in that shard worker process.
3. Persist-on completion throughput remains in mid-40% ratio range despite prior tuning.

Target of this fix:

- decouple receive from durability flush/ack without violating durability ordering.

---

## Scope Lock (MUST follow)

## In scope

1. Persistence writer runtime flow (`main.py`) to split receive from flush/ack.
2. Bounded in-process queues/state needed for decoupling.
3. Additive metrics that prove pipeline health and bottlenecks.
4. Unit/integration tests for new concurrency and ordering guarantees.

## Out of scope

1. Event schema changes.
2. Replay reducer algorithm changes.
3. Checkpoint data model changes.
4. L2/L1/API behavior changes.
5. Retry schedule or send-worker semantics.
6. Changing gate thresholds.

Any out-of-scope change invalidates this iteration evidence.

---

## Non-Negotiable Invariants

These are MUST-preserve invariants:

1. **Segment-before-checkpoint** remains true.
2. **Ack-after-durable-commit** remains true.
3. **No delete/ack before flush commit success**.
4. **Per-shard ordering** for segment sequence remains monotonic.
5. **Replay determinism** remains unchanged (checkpoint + forward segments).
6. **At-least-once transport safety**: crash before ack may redeliver, but dedupe/watermark must keep logical state stable.

---

## Required Architecture Delta

Implement a two-lane per-shard writer process:

1. **Receive/Ingest lane**
   - continuously polls SQS,
   - feeds events into writer buffers via `ingest_events`,
   - does not perform flush/ack I/O directly.

2. **Flush/Ack lane**
   - periodically checks `flush_due(force=False)`,
   - executes durable flush,
   - enqueues committed events for ack,
   - acks in bounded batches/concurrency.

3. **Shared constraints**
   - one flush in-flight per shard process at a time,
   - bounded outstanding committed-not-acked events cap,
   - backpressure behavior is explicit and measured.

---

## Exact Implementation Contract

## Step 1 - Add writer pipeline settings (MUST)

Touch file:

- `src/inspectio/v3/settings.py`

Add settings (or exact equivalent names with mapping documented):

1. `INSPECTIO_V3_WRITER_PIPELINE_ENABLE` (bool, default `true`)
2. `INSPECTIO_V3_WRITER_ACK_QUEUE_MAX_EVENTS` (int, default `20000`, bounds `100..500000`)
3. `INSPECTIO_V3_WRITER_FLUSH_LOOP_SLEEP_MS` (int, default `10`, bounds `1..1000`)
4. `INSPECTIO_V3_WRITER_RECEIVE_LOOP_PARALLELISM` (int, default `1`, bounds `1..4`)

Do not remove existing knobs.

## Step 2 - Refactor `main.py` into explicit tasks (MUST)

Touch file:

- `src/inspectio/v3/persistence_writer/main.py`

Required structure:

1. Create an internal bounded async queue for ack work items.
2. Start separate tasks:
   - `receive_ingest_loop`
   - `flush_loop`
   - `ack_loop`
   - `snapshot_loop` (existing periodic snapshot can remain integrated if equivalent)
3. `receive_ingest_loop`:
   - only receive + ingest + receive metrics.
   - no direct ack calls.
4. `flush_loop`:
   - calls `flush_due(force=False)` on cadence from `FLUSH_LOOP_SLEEP_MS`.
   - every returned event must be pushed to ack queue.
   - if ack queue is full, apply bounded wait/backpressure and record metric.
5. `ack_loop`:
   - pulls ack work, coalesces into batches, calls `ack_many_with_retry`.
   - records ack latency/batch metrics.
6. process shutdown:
   - cancel tasks cleanly,
   - optionally force final flush then drain ack queue best-effort,
   - no silent swallowed fatal errors.

## Step 3 - Keep writer state mutation safe (MUST)

Touch files:

- `src/inspectio/v3/persistence_writer/writer.py`
- `src/inspectio/v3/persistence_writer/main.py`

Rules:

1. Do not call `flush_due` concurrently from multiple tasks.
2. If concurrency risk exists, guard with one flush mutex in `main.py`.
3. `ingest_events` and `flush_due` must not race in ways that corrupt buffer maps.
4. If needed, use one writer-level `asyncio.Lock` around mutation paths.

## Step 4 - Add mandatory observability fields (MUST)

Touch file:

- `src/inspectio/v3/persistence_writer/metrics.py`

Add (global and/or per-shard):

1. `ack_queue_depth_current`
2. `ack_queue_depth_high_water_mark`
3. `ack_queue_blocked_push_total`
4. `flush_loop_iterations_total`
5. `flush_loop_noop_total`
6. `receive_loop_iterations_total`
7. `pipeline_mode` (string marker, e.g. `"decoupled_v1"`)

Snapshots MUST include these fields.

## Step 5 - No changes to durability ordering internals (MUST NOT)

Do not change:

1. segment write before checkpoint write contract logic in `writer.py`.
2. checkpoint schema in `persistence_checkpoint.py`.
3. replay fold semantics in `persistence_recovery/reducer.py`.

---

## Test Contract (Required)

## Unit tests (MUST add/update)

1. `main.py` pipeline behavior:
   - receive can continue while ack queue has pending items.
   - flush loop enqueues ack items only after flush success.
   - ack loop retries preserve retry-safe receipt map behavior.
2. ack queue bounds:
   - full queue increments blocked/backpressure metric.
3. no-duplicate-ack guarantee for a single flush result set.
4. settings bounds/validation.

## Integration tests (MUST)

1. crash after flush commit and before ack:
   - replay remains deterministic after restart.
2. sustained ingest with decoupled loops:
   - no deadlock, no unbounded memory growth in ack queue.
3. existing P12.4-P12.6 suites remain green.

---

## Benchmark Execution Contract

Use WS3.1 hygiene protocol exactly:

1. full stack recycle before off and on runs.
2. off/on shape identical:
   - `duration=240`, `concurrency=120`, `batch=200`.
3. one succeeded / zero failed attempt per job.
4. CloudWatch metric:
   - SQS `NumberOfMessagesDeleted`, period `60`, stat `Sum`, across send shards.
5. active periods >= 5 each profile.
6. datapoint difference <= 1.

---

## Required Artifacts

Under `plans/v3_phases/artifacts/p12_9/iter-6/`:

1. `off_start.txt`, `off_end.txt`
2. `on_start.txt`, `on_end.txt`
3. `off-allpods.log`, `on-allpods.log`
4. `off_job_status.json`, `on_job_status.json`
5. `sustain_summaries.json`
6. `cw_metrics.json`
7. `measurement_manifest.json`
8. `writer_snapshot_extract.json` (or equivalent machine-readable snapshot subset)
9. `ITER6_RESULTS.md`

`ITER6_RESULTS.md` MUST contain:

1. image tag + branch,
2. explicit config delta,
3. completion ratio and comparison against WS3.1 and Iteration 4/5,
4. pipeline metrics summary (queue depth, blocked pushes, loop rates),
5. PROMOTE/NO-GO decision with rule references.

---

## Promotion Gate for this fix

This iteration is **PROMOTE** only if all pass:

1. completion ratio >= `52.66%`,
2. gain vs WS3.1 (`44.84%`) >= `+5.00pp`,
3. no correctness regressions,
4. no stability regressions,
5. evidence proves decoupled pipeline actually ran (`pipeline_mode` + queue metrics present).

Else mark NO-GO and stop for architecture re-plan.

---

## Explicit Forbidden Deviations

AI SE MUST NOT:

1. include unrelated refactors.
2. change multiple performance levers beyond pipeline decoupling.
3. modify replay/checkpoint schemas.
4. skip tests with "existing tests already cover it".
5. claim pass without required artifacts.
6. alter benchmark shape from contract.

---

## PR Checklist (Must all be checked)

- [ ] Only in-scope files changed.
- [ ] Pipeline task split implemented with bounded ack queue.
- [ ] Flush/ack durability invariants preserved.
- [ ] Required metrics added and visible in snapshots.
- [ ] Unit + integration + P12.4-P12.6 suites pass.
- [ ] Hygiene-valid benchmark artifacts committed.
- [ ] `ITER6_RESULTS.md` includes decision and rollback/promote action.
