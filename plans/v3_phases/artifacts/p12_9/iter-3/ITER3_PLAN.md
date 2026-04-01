# P12.9 WS3 Iteration 3 Implementation Plan (SE-Ready)

Companion handoff checklist and command runbook:
`plans/v3_phases/artifacts/p12_9/iter-3/ITER3_SE_HANDOFF_BRIEF.md`

## Goal

Ship a single bounded writer-path tuning iteration that improves persist-on completion throughput versus Iteration 2 and does not regress correctness or stability.

## Numeric targets

- Iteration 2 completion ratio baseline: `45.34%`
- Iteration 1 completion ratio baseline: `52.66%`
- Promotion threshold for Iteration 3: `>= 52.66%` and `>= +5.00pp` over Iteration 2
- Phase hard gate remains: `>= 70.00%` completion on/off

## Root-cause hypotheses

1. Ack fan-out in `ack_many` over-parallelizes `DeleteMessageBatch` calls and increases persist-on tail latency.
2. Flush policy emits too many under-filled flushes under persist-on profile, increasing fixed per-flush overhead.
3. Writer needs bounded concurrency controls and observability to tune safely, not unconstrained parallel work.

## Scope lock (single PR only)

### In scope

1. Add bounded concurrency for ack batch deletes (configurable cap, safe default).
2. Tune flush occupancy behavior to reduce low-value flushes (batch-size/interval interaction only).
3. Add minimal observability fields to prove whether ack/flush overhead improved.

### Out of scope

- Schema or event contract changes.
- Replay/bootstrap/checkpoint semantic changes.
- API behavior changes.
- Multi-iteration experiments in one PR.

## Expected code touch points

- `src/inspectio/v3/persistence_transport/sqs_consumer.py`
  - bounded parallelism in `ack_many`
  - preserve retry-safe receipt-map behavior
- `src/inspectio/v3/persistence_writer/main.py` and/or writer internals
  - flush trigger tuning only (no contract changes)
- `src/inspectio/v3/settings.py`
  - explicit typed settings for ack parallelism and flush tuning knobs
- `src/inspectio/v3/persistence_writer/metrics.py`
  - additive metrics only (non-breaking)
- unit tests under `tests/unit/` for all behavior/metrics changes

## Config contract (must be explicit)

Add or wire settings with safe defaults and bounds:

1. `INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY`
   - integer, default `2`, bounds `1..8`
2. `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS`
   - integer, default chosen by SE based on current writer defaults, bounds `1..writer_flush_batch_max`
3. `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_INTERVAL_MS`
   - keep existing setting if present; if changed, include before/after values in report

If any names differ from existing settings conventions, keep existing names and document mapping in the results report.

## Required tests before deploy

1. `ack_many` tests verify:
   - bounded in-flight delete calls
   - partial batch failure remains retry-safe
   - successful receipts are removed exactly once
2. Flush policy tests verify:
   - flush trigger behavior under low/high ingest
   - no starvation (interval still guarantees eventual flush)
3. Existing writer and observability unit suites remain green.
4. Run persistence correctness suites required by P12.4-P12.6 (or their currently enforced equivalents).

## Benchmark protocol (must match Iteration 2)

1. Build/deploy one image tag for both profiles.
2. Full stack recycle before **off** and before **on** profiles.
3. Load profile for both runs:
   - `python scripts/v3_sustained_admit.py --api-base http://inspectio-l1:8080 --duration-sec 240 --concurrency 120 --batch 200`
4. Persist-off run:
   - `INSPECTIO_V3_PERSIST_EMIT_ENABLED=false`
5. Persist-on run:
   - `INSPECTIO_V3_PERSIST_EMIT_ENABLED=true`
6. Completion metric:
   - CloudWatch `AWS/SQS NumberOfMessagesDeleted`, `Sum`, `Period=60`,
   - summed across `inspectio-v3-send-0..7`,
   - exact windows from `off_start/off_end` and `on_start/on_end`.

## Artifact contract (all required)

Store under `plans/v3_phases/artifacts/p12_9/iter-3/`:

1. `off-allpods.log`
2. `on-allpods.log`
3. `off_start.txt`
4. `off_end.txt`
5. `on_start.txt`
6. `on_end.txt`
7. `sustain_summaries.json`
8. `cw_metrics.json`
9. `ITER3_RESULTS.md`

`ITER3_RESULTS.md` must include:

- image tag
- exact config deltas (before/after values)
- admission off/on and ratio
- completion off/on and ratio
- explicit comparison table vs Iteration 1 and Iteration 2
- go/no-go decision with reason

## Go/No-Go rules

### Go (promote and continue)

All must be true:

1. Completion ratio `>= 52.66%`.
2. Improvement over Iteration 2 is at least `+5.00pp`.
3. No correctness regression.
4. No stability regression (crash loop, unbounded lag, dead writer).

### No-Go (rollback this iteration)

Any true:

1. Completion ratio `< 45.34%`.
2. Completion ratio improves but remains `< 52.66%` with no clear bottleneck movement in metrics.
3. Any correctness suite fails.
4. Any sustained stability violation appears.

## Rollback procedure

1. Redeploy prior known-good image (`iter-2` tag).
2. Restore prior configmap values for changed knobs.
3. Recycle full stack.
4. Run one short sanity benchmark and store evidence in the same folder.

## Iteration 4 pre-authorization (only if Iteration 3 no-go)

Use exactly one variable in Iteration 4 based on Iteration 3 evidence:

1. checkpoint frequency reduction, or
2. flush interval refinement, or
3. retry/backoff jitter smoothing.

## SE execution checklist

- [ ] New branch created for Iteration 3 only.
- [ ] Scope lock respected (no schema/replay/API changes).
- [ ] Tests added/updated and passing.
- [ ] One image built and deployed for both profiles.
- [ ] Full stack recycle executed before both profile runs.
- [ ] Complete artifact contract committed.
- [ ] `ITER3_RESULTS.md` includes decision and next step.
