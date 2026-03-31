# P11 — Persistence Requirements-to-Design Mapping

## Purpose

Map `plans/ASSIGNMENT.pdf` persistence requirements to a design that preserves the current high-throughput v3 pipeline characteristics.

Scope of this document:

- Requirement traceability only (what maps to what).
- No implementation details beyond interface-level design choices.

---

## Assignment Requirements (Persistence) -> Design Mapping

| Assignment requirement | Design decision | Why this satisfies requirement | Throughput guardrail |
|---|---|---|---|
| Persist retry state so it survives restarts (S3-backed durability). | Treat S3 as durable source of truth via append-only persistence events + periodic checkpoints. | Recovery replays durable events after latest checkpoint to rebuild scheduler state. | Hot path does not block on direct S3 per-message writes. |
| Store per message: `messageId`, `attemptCount`, `nextDueAt`, `status`, payload needed for `send` (optional error/history). | Use `PersistenceEventV1` envelope containing those fields (or derivable fields), plus event type. | Every required state field is present in durable history. | Compact event schema; batch serialization. |
| Persist on initial enqueue. | Emit `ENQUEUED` event when message enters scheduler flow. | Initial durable record exists before downstream lifecycle advances. | Event emitted to persistence queue (async), not direct S3 write from request path. |
| Persist after each attempt (success/failure) with updated state. | Emit `ATTEMPT_RESULT` event for every attempt outcome, including next due timestamp when non-terminal. | Durable attempt-by-attempt lifecycle retained. | Attempt processing remains O(1) local + async event emit. |
| Persist terminal states (`success` or `failed`). | Emit `TERMINAL` event for final state. | Durable terminal record available for audit/recovery. | Terminal persistence separated from read-model writes. |
| Restart must continue pending work correctly from persisted state. | Startup recovery: load latest shard checkpoint, replay subsequent segment events, reconstruct pending index and due times. | Pending set and due schedule are reconstructed from durable data. | Recovery is offline/startup path; no runtime prefix scans on every wakeup. |
| S3 key layout example shown (`state/pending/...`, `state/success/...`, `state/failed/...`) is suggestion, not mandate. | Use shard/segment key strategy (e.g. `state/events/<shard>/<yyyy>/<MM>/<dd>/<hh>/<seq>.ndjson.gz` + `state/checkpoints/<shard>/latest.json`). | Assignment allows alternate layout as long as persistence semantics hold. | Segment files amortize object-store overhead. |

---

## Design Constraints Derived from v1/v2 Lessons

These are required to avoid repeating known throughput failures:

1. No per-message synchronous `PutObject` in API or worker hot path.
2. No runtime `list-prefix + sort` scans for scheduling decisions.
3. Separate durability pipeline from outcomes/read-model indexing.
4. Use shard-local buffered segment flushes (size/time based).
5. Use jittered retries for uploader failures; avoid synchronized retry storms.
6. Keep replay deterministic (monotonic shard sequence/checkpoint protocol).

---

## Proposed Persistence Components (Interface-Level)

1. `PersistenceEventEmitter` (hot path dependency)
   - `emit_enqueued(...)`
   - `emit_attempt_result(...)`
   - `emit_terminal(...)`
   - Contract: non-blocking enqueue to persistence transport.

2. `PersistenceWriter` (asynchronous durable writer)
   - Consumes persistence transport.
   - Batches by shard.
   - Flushes compressed segment objects to S3.
   - Updates shard checkpoint.

3. `PersistenceRecovery`
   - Reads checkpoint + forward segments.
   - Reconstructs pending runtime state (`attemptCount`, `nextDueAt`, terminal exclusion).

4. `OutcomeReadModel` (separate concern)
   - Maintains last-100 success/failed API views.
   - Must not be required for scheduler correctness.

---

## Clause-by-Clause Compliance Notes

- Assignment does not require one S3 object per message.
- Assignment requires that state be persisted at lifecycle boundaries; batching is acceptable if durability semantics are preserved.
- Assignment allows helper types/structures and does not constrain internal storage format.
- Assignment requires method signatures to stay intact; persistence components are internal adapters.

---

## Verification Mapping (What Must Be Proven Later)

| Requirement | Verification artifact |
|---|---|
| Initial/attempt/terminal persistence points | Unit tests over emitter call sequence and event payload completeness |
| Recovery correctness after restart | Integration replay tests with synthetic crash points |
| Timing correctness after recovery (`nextDueAt`) | Deterministic clock tests on restored pending set |
| S3 durability semantics | Integration tests against real S3 or high-fidelity harness |
| Throughput preservation | In-cluster benchmark comparing no-persistence mode vs persistence-enabled mode under same load profile |

---

## Non-Goals for This Mapping

- API/schema evolution for user-facing endpoints.
- Detailed queue choice debates (only mapping requirements to design intent).
- Operational rollout steps.
