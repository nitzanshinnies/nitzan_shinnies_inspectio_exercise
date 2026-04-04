# P12.9 Completion Throughput Rescue Plan (Agent-Ready)

## Purpose

Define an execution-ready plan to move persistence-enabled completion throughput from current `hard_fail_completion` status to a passing gate, without regressing assignment correctness or v3 operational stability.

This plan assumes:

- P12.8 shard-aligned persistence transport/writer routing is already implemented and deployed.
- Current completion ratio (persist-on / persist-off) is approximately `50.07%`.
- Gate hard threshold remains `>= 70%`, target threshold remains `>= 85%`.

---

## Current State Snapshot

- Admission throughput is not the limiting dimension.
- Composite gate fails due to completion ratio only (`hard_fail_completion`).
- Stability checks in recent evidence are passing (no crash loop, lag/flush caps pass).
- Remaining work is throughput optimization and measurement confidence, not basic architecture enablement.

---

## Non-Negotiable Constraints

1. Keep persistence semantics assignment-compliant (no data-loss shortcuts).
2. No synchronous S3 writes in API/worker hot paths.
3. No reintroduction of singleton persistence bottlenecks.
4. Every optimization change must include a measurement rerun and artifacts.
5. Full stack recycle before each off/on benchmark profile pair.

---

## Success Criteria

## Phase success (P12.9 complete)

- Completion hard gate passes: completion ratio `>= 70%`.
- No correctness regression in P12.4-P12.6 suites.
- No stability regression (crash loops, unbounded lag, writer deadlocks).

## Stretch success (P12.9 target)

- Completion target gate passes: completion ratio `>= 85%`.

---

## Execution Strategy

Run in four sequential workstreams. Do not overlap streams in the same PR.

## WS1 - Measurement Integrity Lock (must run first)

### Goal

Ensure the completion signal is trustworthy before tuning.

### Tasks

- Standardize one benchmark profile pair (`persist-off`, `persist-on`) with identical:
  - image tag,
  - deployment replica layout,
  - queue/shard config,
  - load job shape and duration,
  - CloudWatch period/statistic.
- Reconfirm completion metric query:
  - sum `AWS/SQS NumberOfMessagesDeleted` across active send shards,
  - aligned exact time windows from job start/end markers.
- Add a machine-readable query manifest to artifacts:
  - namespace,
  - metric name,
  - dimensions list (all shard queue names),
  - period,
  - stat,
  - start/end.

### Deliverables

- `plans/v3_phases/artifacts/p12_9/measurement_manifest.json`
- `plans/v3_phases/artifacts/p12_9/persist-off-window.txt`
- `plans/v3_phases/artifacts/p12_9/persist-on-window.txt`
- `plans/v3_phases/artifacts/p12_9/benchmark_metrics_raw.json`

### Exit criteria

- Completion throughput values are reproducible across two consecutive reruns (`<= 10%` variance per profile).

---

## WS2 - Writer Hot-Path Observability Expansion

### Goal

Localize the exact persistence bottleneck before tuning.

### Tasks

- Add per-shard writer metrics:
  - receive batch size (`events`),
  - ingest rate (`events/sec`),
  - flush batch size (`events/flush`),
  - flush payload bytes (`bytes/flush`),
  - flush duration (`ms`),
  - ack batch size and ack latency,
  - retry counts by operation (`s3_put`, checkpoint update, ack),
  - queue polling idle ratio.
- Add per-shard lag gauges:
  - transport queue oldest age,
  - events buffered in memory,
  - flush wait age (oldest buffered event age).
- Emit periodic writer health snapshots to logs (fixed cadence, parse-friendly).

### Deliverables

- Metrics implementation PR + tests.
- `plans/v3_phases/artifacts/p12_9/writer_observability_snapshot.md`.

### Exit criteria

- For each shard, at least one full on-run provides complete metric series with no missing dimensions.

---

## WS3 - Throughput Tuning Iterations (bounded, evidence-driven)

### Goal

Raise persist-on completion throughput without compromising correctness.

### Active implementation packet

- Iteration 3 (SE-ready): `plans/v3_phases/artifacts/p12_9/iter-3/ITER3_PLAN.md`
- Iteration 3 rerun hygiene fix: `plans/v3_phases/P12_9_WS3_1_RERUN_MEASUREMENT_HYGIENE_FIX_SPEC.md`

### Tuning levers (in order)

1. **Flush policy tuning**
   - Increase effective flush batch occupancy before interval triggers.
   - Tune flush interval to reduce small-flush overhead.
2. **Ack strategy tuning**
   - Batch acknowledgements more efficiently post-flush.
   - Avoid serialized ack bottlenecks when safe.
3. **Write pipeline parallelism**
   - Introduce bounded concurrency in writer pipeline where ordering contract allows.
   - Keep per-shard deterministic sequence guarantees.
4. **Checkpoint write amplification control**
   - Reduce checkpoint write frequency while preserving recovery invariants.
   - Never violate segment-before-checkpoint contract.
5. **Backoff and retry tuning**
   - Calibrate S3 and transport retry backoff to avoid synchronized stalls.

### Iteration protocol

- One tuning change per iteration PR.
- Run off/on rerun after each merged iteration.
- Stop and rollback the iteration if:
  - correctness tests fail,
  - crash loop appears,
  - completion ratio drops by `>= 10%` from prior best,
  - lag cap is breached.

### Deliverables per iteration

- `plans/v3_phases/artifacts/p12_9/iter-<n>/`:
  - config diff,
  - run logs,
  - CloudWatch export,
  - report delta summary.

---

## WS4 - Gate Closure and Freeze

### Goal

Produce final reproducible evidence bundle and freeze known-good config.

### Tasks

- Execute final controlled off/on pair with locked image and config hashes.
- Regenerate throughput report with composite gate output.
- Record final operational runbook:
  - deploy steps,
  - rollback steps,
  - must-watch dashboards/alerts.

### Deliverables

- Updated `plans/v3_phases/P12_7_THROUGHPUT_REPORT.md`.
- `plans/v3_phases/P12_9_ROLLOUT_AND_GATE_CLOSURE_REPORT.md`.
- Frozen config snapshot + image tag references.

### Exit criteria

- `classification` is `hard_pass_target_miss` or `target_pass`.
- No open correctness/stability blockers.

---

## PR and Branching Plan

Use one branch per workstream/iteration:

- `feat/v3-p12-9-measurement-lock`
- `feat/v3-p12-9-writer-observability`
- `feat/v3-p12-9-tuning-iter-1`
- `feat/v3-p12-9-tuning-iter-2`
- `feat/v3-p12-9-gate-closure`

Rule: one concern per PR; include tests and artifacts in same PR.

---

## Test and Validation Matrix (required before merge)

1. Unit tests for any new metric or writer-path logic.
2. Integration tests for writer batching/ack ordering semantics.
3. Existing persistence correctness suites (P12.4-P12.6) green.
4. Throughput comparison rerun with artifact bundle.
5. Gate report generated from fresh evidence, not historical reuse.

---

## Rollback Policy

Rollback triggers:

- completion ratio drops materially versus pre-change baseline,
- correctness regression,
- crash-loop or sustained lag breach.

Rollback actions:

1. Revert to last known-good image tag.
2. Reapply last known-good configmap snapshot.
3. Scale back any new writer topology changes if introduced.
4. Re-run a short validation benchmark and attach evidence.

---

## Risks and Mitigations

- **Risk:** Optimize against noisy measurements.
  - **Mitigation:** WS1 reproducibility lock before tuning.
- **Risk:** Throughput gains break replay/correctness.
  - **Mitigation:** Mandatory P12.4-P12.6 regression suite on every iteration.
- **Risk:** Hidden shard skew causes partial gains.
  - **Mitigation:** Per-shard observability and shard-level comparison tables.
- **Risk:** IAM/S3 policy drift invalidates conclusions.
  - **Mitigation:** record live role/policy assumptions and verify before each rerun.

---

## Execution Checklist

- [x] WS1 completed with reproducible completion metrics.
- [ ] WS2 merged with per-shard bottleneck visibility.
- [x] At least one WS3 iteration completed with measurable gain (Iteration 3: +7.10pp vs Iteration 2, no-go on threshold miss).
- [ ] Final gate rerun artifacts committed.
- [ ] Completion hard gate `>= 70%` achieved.
- [ ] P12.9 closure report published.

