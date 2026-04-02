# P1 — L2 HTTP, OpenAPI, stub enqueue

**Goal:** **L2** FastAPI routes (**4.1**), **idempotency** (**4.2**), **`BulkIntentV1`** enqueue via injectable backend (in-memory queue for tests). Admission **O(1) in N** at HTTP layer: **one** **`BulkIntentV1`** per **`/messages/repeat`** (**3.2**).

**Needs:** P0.

**Refs:** **`plans/openapi.yaml`**; master **4.1**, **4.2**, **4.8** (GET wired in P4).

## Done when

- [ ] Routes: **`POST /messages`**, **`POST /messages/repeat?count=`**, **`GET /messages/success|failed`**, **`GET /healthz`**.
- [ ] **OpenAPI-first:** any shape change lands in **`plans/openapi.yaml`** before or in the same PR as code.
- [ ] **Repeat:** single body + **`count`**; no N parallel posts (aligns with master plan **L1** coalescing).
- [ ] **Single message:** implement as **`BulkIntentV1`** with **`count=1`** (uniform path).
- [ ] **Idempotency-Key** (header and/or body if spec adds it): duplicate within TTL → same **`batchCorrelationId`**, **no** second enqueue (**4.2**); in-process TTL OK for dev; document multi-replica gap until Redis dedupe.
- [ ] **GET outcomes:** stub **`{ "items": [] }`** or documented **503** until P4 + Redis (**4.8**).
- [ ] **`Clock`**: inject **`now_ms()`** for tests.
- [ ] **`TestClient` / AsyncClient** tests (**unit** with stub enqueue).

## OpenAPI (v3 alignment)

- **Repeat response:** master plan traceability row **Repeat response** (section **0**) — **summary** vs full **`messageIds`**; choose one and update spec. Large N favors summary (**3.2**).
- Drop or nullable **`ingestSequence`** if no journal.
- **`shardId` on admit:** omit or document predicted **`hash % K`** — match implementation.
- If L2 reads Redis for outcomes in P4, simplify or deprecate **`notification-internal`** paths in the spec so agents do not build unused services.

## Tests

| Marker | Cover |
|--------|--------|
| unit | healthz; single + repeat enqueue depth; idempotency; 400s |

## Out of scope

SQS, expander, worker, L1, Redis.

**Next:** P2 swaps stub for **`SqsBulkEnqueue`** (**INSPECTIO_V3_BULK_QUEUE_URL**).
