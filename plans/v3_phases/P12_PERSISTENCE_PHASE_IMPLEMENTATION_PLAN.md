# P12 — Persistence Phase Implementation Plan (Agent-Ready)

## Purpose

Provide a detailed, execution-ready phase plan for AI agents to implement assignment-compliant persistence while preserving high-throughput behavior demonstrated in v3 performance runs.

Session recovery handoff:

- `plans/v3_phases/P12_9_SESSION_RECOVERY_PLAN.md`

Architecture intent (S3 as pure async backup; scheduler uses memory + SQS only):

- `plans/v3_phases/P12_9_PERSISTENCE_ASYNC_BACKUP_DECISION_RECORD.md`

This plan extends:

- `plans/ASSIGNMENT.pdf`
- `plans/v3_phases/P11_PERSISTENCE_REQUIREMENTS_TO_DESIGN_MAPPING.md`

This document is implementation sequencing and verification guidance only.

---

## Global Constraints (Non-Negotiable)

1. No synchronous S3 writes in API or worker per-message hot paths.
2. No runtime prefix scans (`list + sort`) for due scheduling.
3. Persistence durability path must be decoupled from outcomes/read-model path.
4. Replay must be deterministic from checkpoint + forward segments.
5. Existing public API shapes remain unchanged unless explicitly approved.

---

## Decision Record (Must Be Locked Before P12.1)

Agents must not start implementation until these decisions are written in the PR description and reflected in code comments/config:

1. **Durability mode**
   - `strict`: enqueue/attempt/terminal processing fails if persistence event cannot be handed off.
   - `best_effort`: processing continues, but drops are counted/alerted.
2. **Transport type and ordering guarantees**
   - Queue/stream choice, ordering semantics, dedupe behavior.
3. **Checkpoint atomicity contract**
   - Exact write order between segment object and checkpoint update.
4. **Replay conflict policy**
   - How duplicate or conflicting events are folded (idempotent reducer rules).
5. **Backpressure policy**
   - What happens when persistence transport/writer lags beyond threshold.

Without these explicit locks, a phase is considered incomplete even if tests are green.

---

## Core Invariants (Must Hold in Every Phase)

1. For each `messageId`, reduced state is monotonic:
   - `attemptCount` never decreases.
   - `status` transitions only `pending -> success|failed` (terminal is final).
2. Replay is deterministic:
   - Replaying the same persisted data yields identical runtime state.
3. Terminal idempotency:
   - Duplicate terminal events do not create duplicate logical terminals.
4. No scheduler dependency on read-model:
   - `/messages/success|failed` storage failures cannot break retry correctness.
5. No unbounded memory growth:
   - Buffers and lag queues have configured hard caps and metrics.

---

## Forbidden Shortcuts

- Writing one S3 object per message attempt in hot path.
- Using S3 `list-prefix` scans for runtime due scheduling.
- Treating read-model records as scheduler source of truth.
- Marking phase done without fault-injection coverage for that phase's failure modes.

---

## Phase Overview

```text
P12.0 Contracts and test harness
P12.1 Persistence event model + emitter interfaces
P12.2 Async persistence transport integration
P12.3 Persistence writer (segment + checkpoint to S3)
P12.4 Recovery replay and runtime bootstrap
P12.5 Read-model hardening and failure isolation
P12.6 Correctness and fault-injection verification
P12.7 Throughput validation and regression gates
P12.8 Sharded persistence transport and writer scaling
P12.9 Completion throughput rescue and gate closure
```

Each phase is mergeable and must ship with tests.

---

## P12.0 — Contracts and Test Harness

### Goal

Lock persistence contracts and add test scaffolding before service changes.

### Tasks

- [x] Define canonical persistence event schema (versioned envelope).
- [x] Define checkpoint schema and replay ordering rules.
- [x] Add deterministic clock and fake transport fixtures for replay tests.
- [x] Add throughput benchmark harness extension points (persist on/off toggles).

### Expected file touch points

- `src/inspectio/v3/schemas/` (new persistence schemas)
- `tests/unit/` (schema/replay-order tests)
- `tests/integration/` (fake durability path)

### Acceptance criteria

- [x] Event and checkpoint schemas have strict validation tests.
- [x] Replay-order tests prove stable reconstruction from unordered delivery + ordered storage.
- [x] No runtime behavior changes yet.
- [x] Decision Record section above is fully resolved and documented
  (`plans/v3_phases/P12_DECISION_RECORD.md`).

---

## P12.1 — Persistence Event Model + Emitter Interfaces

### Goal

Introduce internal persistence interfaces without changing behavior.

### Tasks

- [x] Add `PersistenceEventEmitter` abstraction with:
  - `emit_enqueued`
  - `emit_attempt_result`
  - `emit_terminal`
- [x] Add no-op emitter implementation (default safe baseline).
- [x] Wire emit hooks at lifecycle boundaries:
  - enqueue
  - per attempt result
  - terminal transition

### Expected file touch points

- `src/inspectio/v3/worker/`
- `src/inspectio/v3/l2/` (for enqueue lifecycle signal)
- `src/inspectio/v3/settings.py` (feature flags)

### Acceptance criteria

- [x] Unit tests assert emit call sequence and payload completeness.
- [x] Baseline mode (no-op emitter) passes full test suite with no behavior regression.

---

## P12.2 — Async Persistence Transport Integration

### Goal

Move durability handoff to asynchronous transport (queue-based), not direct S3.

### Tasks

- [x] Add transport producer/consumer contracts.
- [x] Implement producer in emitter path with bounded retry + jitter.
- [x] Add DLQ/error policy for producer failures.
- [x] Add config flags for transport URL, retries, batch controls.

### Expected file touch points

- `src/inspectio/v3/sqs/` (or dedicated persistence transport module)
- `src/inspectio/v3/settings.py`
- Kubernetes config docs/manifests for new envs

### Acceptance criteria

- [x] Integration test proves enqueue/attempt/terminal events are handed off under load.
- [x] Producer failures do not crash worker or API processes.
- [x] Backpressure behavior is explicit and tested (lag growth trigger and handling).

---

## P12.3 — Persistence Writer (Segment + Checkpoint to S3)

### Goal

Implement durable batched writer consuming persistence events and writing S3 segments.

### Tasks

- [x] Build shard-local buffers with size/time flush triggers.
- [x] Write compressed segment objects with monotonic shard sequence.
- [x] Persist checkpoint atomically after successful segment write.
- [x] Add idempotent write semantics for replayed transport messages.
- [x] Add writer metrics:
  - events buffered/flushed
  - flush duration
  - S3 errors/retries
  - lag to durable commit

### Expected file touch points

- `src/inspectio/v3/persistence_writer/` (new module)
- `deploy/kubernetes/` (writer workload + config)
- `tests/integration/` (S3/localstack writer tests)

### Acceptance criteria

- [x] Writer flushes are batched; no object-per-message pattern exists.
- [x] Checkpoint monotonicity and idempotency are verified by tests.
- [x] Writer must restart without duplicate logical state.
- [x] Segment-before-checkpoint durability contract is tested with crash injection.

---

## P12.4 — Recovery Replay and Runtime Bootstrap

### Goal

Rebuild pending scheduler state from checkpoint + forward segments on startup.

### Tasks

- Implement replay engine:
  - load checkpoint
  - enumerate subsequent segments in sequence
  - fold events into runtime state
- Reconstruct:
  - pending set
  - `attemptCount`
  - `nextDueAt`
  - terminal exclusion set
- Add startup reconciliation logging and counters.

### Expected file touch points

- `src/inspectio/v3/worker/` bootstrap
- `src/inspectio/v3/persistence_recovery/` (new module)
- `tests/integration/` recovery scenarios

### Acceptance criteria

- Crash/restart tests demonstrate no loss of pending work.
- Recovered `nextDueAt` values satisfy assignment timing rules.
- Recovery avoids runtime S3 prefix scans in steady state.
- Replay reducer enforces Core Invariants under duplicates and out-of-order events.

---

## P12.5 — Read-Model Hardening and Failure Isolation

### Goal

Ensure outcomes/read APIs do not affect scheduler correctness or throughput.

### Tasks

- Keep outcomes updates asynchronous and isolated from scheduler durability.
- Confirm read-model write failures do not crash worker processing.
- Keep API `/messages/success` and `/messages/failed` semantics intact (last 100).

### Expected file touch points

- `src/inspectio/v3/outcomes/`
- worker terminal handling path
- tests for degraded read-model backend

### Acceptance criteria

- Worker remains stable when outcomes backend is unavailable.
- Terminal durability remains correct independently of read-model health.
- Read-model degradation is visible via metrics/counters and does not silently mask errors.

---

## P12.6 — Correctness and Fault-Injection Verification

### Goal

Prove persistence correctness under adverse conditions.

### Test matrix

1. Crash between event emission and transport ack.
2. Crash after segment write but before checkpoint update.
3. Duplicate transport delivery.
4. Out-of-order transport delivery across shards.
5. Temporary S3 failures with retry.
6. Writer restart during high ingest.

### Acceptance criteria

- No lost pending messages after restart/recovery.
- No duplicate terminal application for same message lifecycle.
- Replay converges to same state across repeated runs.
- All matrix scenarios run in CI or a documented nightly suite with reproducible commands.

---

## P12.7 — Throughput Validation and Regression Gates

### Goal

Demonstrate persistence-enabled mode retains the required throughput envelope defined by the gate criteria below.

### Bench profiles

- Baseline A: persistence disabled/no-op.
- Baseline B: persistence enabled with writer running.
- Stress: peak profile used in v3 throughput runs.

### Required outputs

- Admit throughput (`SUSTAIN_SUMMARY`).
- Combined send-queue delete throughput (CloudWatch sum across active shards).
- Writer lag metrics and flush latency.
- Error-rate deltas between A and B.

### Gate criteria

- **Hard gate (initial):** persistence-enabled throughput must be at least **70%** of no-op baseline under identical load profile.
- **Target gate (after tuning):** persistence-enabled throughput must reach at least **85%** of no-op baseline.
- Stable operation (no crash loops, no unbounded lag growth).
- Assignment persistence semantics validated concurrently.
- If hard gate fails, merge is blocked unless an explicit temporary waiver is approved and documented.

---

## P12.8 — Sharded Persistence Transport and Writer Scaling

### Goal

Remove the centralized persistence bottleneck by aligning persistence transport + writer ownership
with send-path shard parallelism.

### Tasks

- [x] Add shard-aware persistence transport settings + strict startup validation.
- [x] Route emitted events to shard-mapped transport producers by `event.shard`.
- [x] Bind writer process queue ownership using `INSPECTIO_V3_WRITER_SHARD_ID`.
- [x] Add Kubernetes writer-per-shard template and env wiring documentation.
- [x] Add unit/integration tests for shard routing and shard binding guards.

### Acceptance criteria

- [x] Persistence transport routing is shard-aligned with no cross-shard queue leakage.
- [x] Writer shard id validation fails fast for out-of-range or mismatched queue maps.
- [x] Existing checkpoint and replay behavior remains shard-local and deterministic.
- [x] New P12.8 tests pass with existing persistence correctness suites.

---

## P12.9 — Completion Throughput Rescue and Gate Closure

### Goal

Recover persistence-enabled completion throughput to pass the composite gate while preserving correctness and stability guarantees from P12.4-P12.8.

### Plan reference

- `plans/v3_phases/P12_9_COMPLETION_THROUGHPUT_RESCUE_PLAN.md`
- Active WS3 execution packet: `plans/v3_phases/artifacts/p12_9/iter-3/ITER3_PLAN.md`
- Active WS3 rerun hygiene fix: `plans/v3_phases/P12_9_WS3_1_RERUN_MEASUREMENT_HYGIENE_FIX_SPEC.md`

### Acceptance criteria

- Completion hard gate passes (`>= 70%` on/off ratio) under reproducible off/on benchmark profiles.
- No regression in persistence correctness and restart safety suites.
- Stability signals remain healthy (no crash loops, lag/flush caps pass).

---

## Agent Execution Rules

1. One phase per PR unless phase is explicitly tiny.
2. Add/update tests in the same PR as behavior changes.
3. Do not mix infra scale experiments with schema/logic refactors in one PR.
4. Keep feature flags default-safe for incremental rollout.
5. Record benchmark config and image tags in plan/update docs for every perf claim.

---

## Deliverables Checklist (for completion)

- [ ] Persistence event schemas and contracts
- [ ] Async persistence transport handoff
- [ ] Batched S3 segment writer + checkpoints
- [x] Deterministic replay recovery
- [x] Outcomes isolation from durability path
- [x] Fault-injection correctness tests
- [x] Throughput comparison report (persist off vs on)
- [x] Shard-aligned persistence routing/writer scaling
- [ ] Completion throughput rescue and gate closure (P12.9)
- [ ] Decision Record resolved and committed
- [ ] Core Invariants validated in automated tests

