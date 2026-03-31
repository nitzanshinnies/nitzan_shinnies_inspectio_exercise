# P12 Decision Record (Locked Before P12.1)

This record satisfies the "Decision Record" lock in
`plans/v3_phases/P12_PERSISTENCE_PHASE_IMPLEMENTATION_PLAN.md`.

## 1) Durability mode

- **Locked mode for rollout:** `best_effort` (default-safe in P12.0/P12.1 scaffolding).
- Rationale: avoids production traffic interruption while event model and transport are introduced.
- Guardrail: dropped handoff attempts must be counted/observable (to be wired in P12.1/P12.2 metrics).
- Future option: `strict` can be introduced as an opt-in config for controlled environments.

## 2) Transport type and ordering guarantees

- **Transport:** asynchronous queue-based handoff (SQS-standard compatible semantics).
- Ordering guarantee: transport delivery may be duplicated or reordered.
- Deterministic replay order therefore comes from persisted metadata:
  `shard`, `segmentSeq`, `segmentEventIndex` (+ stable tie-breaker `eventId`).

## 3) Checkpoint atomicity contract

- Writer must only advance checkpoint **after** successful segment object durability.
- Contract is "segment-before-checkpoint":
  1) persist segment object,
  2) persist checkpoint pointing at that segment sequence.
- Crash between (1) and (2) is recoverable by replaying segment without checkpoint advance.

## 4) Replay conflict policy

- Reducer is idempotent and monotonic by `messageId`:
  - `attemptCount` never decreases,
  - terminal state is final,
  - duplicate terminal events are ignored logically.
- Out-of-order events are sorted by deterministic replay order before folding.

## 5) Backpressure policy

- Persistence handoff path must be bounded:
  - fixed-capacity in-memory queue/buffer per producer.
- Behavior when lag threshold is exceeded:
  - `best_effort`: continue message flow, increment lag/drop counters and alert.
  - `strict` (future optional): reject/abort the processing unit.

---

Locked in P12.0 and referenced by schemas/recovery comments and tests.
