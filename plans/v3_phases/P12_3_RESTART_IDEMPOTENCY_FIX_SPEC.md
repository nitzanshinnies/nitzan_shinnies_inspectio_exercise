# P12.3 Fix Spec — Writer Restart Idempotency

## Context

Current P12.3 implementation satisfies batching and segment-before-checkpoint durability ordering, but does not fully prove:

> "Writer can restart without duplicate logical state."

Observed gap:

- Writer dedupe is process-local (`_seen_event_ids` in memory).
- After restart, transport redelivery of already-durable events can be re-flushed.
- Existing tests do not explicitly validate restart+redelivery idempotency.

This spec defines the required fix.

---

## Problem Statement

The writer currently computes segment keys from in-memory `next_segment_seq` loaded from checkpoint.
If transport redelivers events from a segment already durably written before restart, the writer can:

1. write a new segment containing duplicates, and
2. advance checkpoint,

which violates "restart without duplicate logical state."

---

## Required Outcome

After restart, replayed/redelivered transport events that are already represented in durable state must not create additional logical lifecycle effects.

Equivalent requirement:

- For each `(messageId, eventId)` pair, durable store behaves exactly-once at logical level, even if transport is at-least-once and writer restarts.

---

## Scope

In scope:

- Writer dedupe durability semantics across restart.
- Checkpoint/segment metadata changes required for restart-safe idempotency.
- Unit + integration tests proving restart idempotency.

Out of scope:

- P12.4 replay bootstrap redesign (except metadata compatibility needed by this fix).
- Changing user-facing API behavior.

---

## Normative Design Requirements

### R1 — Persisted idempotency watermark

Checkpoint must include enough monotonic progress metadata to reject already-committed events after restart.

Minimum requirement:

- Persist highest committed `(segmentSeq, segmentEventIndex)` per shard.
- Writer must discard any incoming event with ordering key <= checkpoint watermark.

If event ordering key is not globally monotonic in producer today, the SE must make it monotonic (see R2).

### R2 — Stable event ordering key

Event ordering key used by writer must be deterministic and monotonic per shard across restarts:

- Prefer producer-assigned `segmentSeq` + `segmentEventIndex` monotonic per shard.
- If not guaranteed, add a dedicated monotonic `eventOrdinal` field in persistence event schema.

Writer logic must not rely on wall clock or random UUID ordering for dedupe.

### R3 — Restart-safe flush gate

Before writing a shard flush batch:

1. Filter out all events at/below committed watermark.
2. If filtered batch is empty, ack without writing segment/checkpoint.
3. If non-empty, write segment then checkpoint with new watermark.

### R4 — Idempotent checkpoint advance

Checkpoint advance must be strictly monotonic.

- On concurrent/retry paths, checkpoint must never move backward.
- Duplicate checkpoint writes for same watermark are allowed.
- Segment write retries must not produce multiple logical commits for same watermark window.

### R5 — Transport redelivery tolerance

With at-least-once delivery and writer restart:

- Redelivered events that were previously committed must be dropped deterministically.
- No additional segment containing only already-committed events may be written.

---

## Implementation Notes (SE Guidance)

1. Extend `PersistenceCheckpointV1` if needed (backward-compatible read):
   - add committed watermark fields explicitly if current fields are insufficient.
2. Update `BufferedPersistenceWriter`:
   - initialize per-shard committed watermark from checkpoint,
   - filter buffered events by watermark before `_flush_shard`,
   - only advance watermark after successful checkpoint write.
3. Keep segment-before-checkpoint contract unchanged.
4. Maintain existing metrics and add:
   - `events_dropped_committed_watermark`
   - `empty_flushes_due_to_dedupe`

---

## Test Requirements (Must Add)

### Unit tests

1. **Restart redelivery drop**
   - Given checkpoint watermark X and incoming events <= X,
   - writer flush does not write segment/checkpoint,
   - events are acknowledged.

2. **Mixed batch filtering**
   - Batch contains events <= X and > X,
   - writer writes only > X,
   - checkpoint advances to max committed in batch.

3. **Monotonic checkpoint safety**
   - Simulate retry/race sequence,
   - checkpoint never decreases.

4. **Backward compatibility**
   - Old checkpoint payload (without new fields if added) still loads safely.

### Integration test (mandatory)

`test_writer_restart_redelivery_idempotent`:

1. Ingest and flush batch A (durable commit).
2. Simulate process restart (new writer instance from same store/checkpoint).
3. Redeliver same transport events from batch A.
4. Flush/ack.
5. Assert:
   - no new logical events committed,
   - no duplicate durable effects,
   - checkpoint remains monotonic and unchanged (or unchanged logically).

---

## Acceptance Criteria

This fix is complete only if all are true:

1. Restart+redelivery integration test passes.
2. Existing P12.3 tests remain green.
3. No regression in segment-before-checkpoint durability contract tests.
4. Writer metrics expose dropped-already-committed events.
5. Full test suite passes.

---

## Rollout and Risk Controls

- Feature default remains safe; no API changes.
- If schema fields are added:
  - support reading old checkpoint format,
  - write new format only after code supports both.
- Include migration note in PR description.

---

## PR Checklist for SE

- [ ] Implement watermark-based restart dedupe in writer
- [ ] Update checkpoint schema/reader compat (if needed)
- [ ] Add required unit tests
- [ ] Add mandatory restart+redelivery integration test
- [ ] Preserve segment-before-checkpoint contract
- [ ] Add dedupe/watermark metrics
- [ ] Run `pytest tests/` and attach results
