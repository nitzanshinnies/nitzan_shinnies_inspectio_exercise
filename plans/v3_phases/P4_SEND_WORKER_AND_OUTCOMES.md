# P4 — Send worker (L4), outcomes (4.5–4.8)

**Goal:** **L4**: per-**`messageId`** mutex (**4.5**), **`wakeup`** every **~500 ms** (PDF **exact** cadence per master plan; concurrent with receive—**4.5**) without starving **ReceiveMessage**, **absolute** retry deadlines (**4.7**), **`try_send` → bool`** default **`True`** (**4.6**), **failed** terminal after **6-th failed `try_send`** (**4.7** / PDF retry row). **Never** invoke **`try_send`** before **`nextDueAt`** (PDF NFR **time**). **Outcomes:** shared store (**4.8**) — **Redis**, **ElastiCache** (master **9**), or a **small dedicated outcomes service**; not an in-memory dict on L2 if **replicas > 1**. Optional **L5**: no-op enqueue to **`INSPECTIO_V3_PERSIST_QUEUE_URL`**.

**Needs:** P3.

**Refs:** OpenAPI **`OutcomeItem`** / **`MessageTerminalV1`**; master **8** (log **`messageId`**, **`shard`**; counters **`send_ok`**, **`send_fail`**).

## Done when

- [ ] Worker entrypoint (e.g. **`python -m inspectio.v3.worker.main`**); model **one consumer per send queue** or **shard index** env—**document**.
- [ ] **Receive loop** + **timer/multiplex**: **`wakeup`** scans due work; **long poll** + **batch receive** where it helps throughput (**3.2**, **7.2**).
- [ ] On **`SendUnitV1`**: **newMessage-equivalent** → run **attempt #1** immediately when the unit is first handled (**4.7**); **`asyncio.Lock`** per id (**4.5**). PDF **thread-safe** `send`: achieve exclusion via this lock (single event loop is not multi-threaded, but lock still serializes concurrent **tasks** for one id).
- [ ] On **`try_send` False**: schedule next attempt at **`receivedAtMs + offset`** for attempts **2..6**; on **6th failure** → **failed** outcome, discard active state (**4.7**). On **`True`** → **success** outcome; **`attemptCount`** **1–6** per OpenAPI.
- [ ] **Redis** lists (or zset) capped at **100** per success/failed; **most recent first** for **GET** (**4.8**). L2 GET handlers read same store—**no** in-process-only outcomes with multiple L2 replicas.
- [ ] **SQS delete** after terminal persisted and safe (or documented ordering).
- [ ] **Redelivery:** duplicate **`SendUnitV1`** must not double-run side effects—dedupe by **`message_id`** in worker or idempotent state rebuild from message.
- [ ] **e2e** (compose): api + redis + localstack + expander + worker; repeat **count=10** → poll success (**full stack recycle** before run per workspace rules).
- [ ] **README** (master **6**, rule **6**): structures, sync, complexity, **gaps** (**AC5** / no S3 recovery), AWS run, **planned S3 schema** for a later wave.

## Layout (suggested)

`v3/worker/` (runtime, per-message state, **`try_send`**), `v3/outcomes/redis_store.py`.

## Tests

| Marker | Cover |
|--------|--------|
| unit | due times; six failures → terminal; wakeup without new message; per-id serialization |
| integration | redis append + read + limit |
| e2e | compose path (gated) |

## Out of scope

**mock-sms** HTTP (**4.6**), S3 journal, L1.

**Next:** P5 L1 proxy; optional **L1** in compose after P5.
