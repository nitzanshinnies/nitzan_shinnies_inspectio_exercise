# TEST_LIST.md - Full enumerated test cases (Section 9.1)

Companion to [`plans/TESTS.md`](TESTS.md): a **concrete checklist** of test cases, including **edge cases**, for implementation and review. Each case should map to one or more automated tests (or a documented manual step).

**Legend:** **U** = unit, **I** = integration, **E** = end-to-end / multi-component.

---

## 1) Sharding and ownership

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-SH-01 | U | Same `messageId` and `TOTAL_SHARDS` always yields the same `shard_id`. | Vary process restart / re-import; hash must be stable. |
| TC-SH-02 | U | `shard_id` is always in `[0, TOTAL_SHARDS - 1]`. | `TOTAL_SHARDS = 1` (only shard 0). |
| TC-SH-03 | U | Changing `TOTAL_SHARDS` changes mapping (document as migration); **baseline** test uses fixed `TOTAL_SHARDS`. | **Optional:** single messageId maps differently when `TOTAL_SHARDS` differs. |
| TC-SH-04 | U | Owned range for `pod_index` P equals `range(P * spp, (P+1) * spp)` for given `shards_per_pod` (spp). | P = 0, last pod, **spp * num_pods == TOTAL_SHARDS**. |
| TC-SH-05 | U | **Non-owner** processing path: message with `shard_id` outside owned set → **no** pending writes / skip. | Inject “foreign shard” pending in list simulation. |
| TC-SH-06 | U | `HOSTNAME` parsing → `pod_index` for `worker-0`, `worker-1`, and realistic StatefulSet FQDN if implementation supports. | Malformed hostname: **defined behavior** (fail fast vs default). |
| TC-SH-07 | I | Bootstrap list-objects/list-prefix limited to **`state/pending/shard-<id>/`** for **owned** ids only. | No full-bucket scan. |

---

## 2) Retry timeline and `attemptCount`

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-RT-01 | U | After failure at **attempt #1** (`attemptCount=0` per spec convention), `nextDueAt` = `now + 500ms` (0.5s). | Use injectable `now`. |
| TC-RT-02 | U | After failure at **#2..#5**, delays **2s, 4s, 8s, 16s** respectively (relative to attempt time). | Table-driven golden values. |
| TC-RT-03 | U | After **6th failed attempt** (`attemptCount == 6`), **no** seventh schedule—terminal **failed** transition. | Boundary: do not off-by-one. |
| TC-RT-04 | U | While `attemptCount < 6`, pending record updated **in place** with monotonically increasing `attemptCount` and new `nextDueAt`. | Re-read after failed send. |
| TC-RT-05 | U | Successful send with `attemptCount in {0..5}` moves to **success** (never increments past success). | Success on first try vs after retries. |
| TC-RT-06 | U | `attemptCount` never **below 0** or **above 6** on persisted pending. | Corrupt input in **recovery** tests (see TC-RQ-*). |

---

## 3) Wakeup loop and due selection

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-WU-01 | U | At tick time `T`, only messages with `nextDueAt <= T` are eligible. | `nextDueAt == T` **is** due (inclusive). |
| TC-WU-02 | U | Messages with `nextDueAt > T` are **not** sent on this tick. | One tick before due. |
| TC-WU-03 | U | Among due messages, processing order is **non-decreasing `nextDueAt`** (earliest first); ties broken **deterministically** (document rule, e.g. `messageId`). | Two messages same `nextDueAt`. |
| TC-WU-04 | U | **500ms cadence:** over simulated time, tick count × 500ms matches elapsed time (allowing implementation’s alignment to first tick). | Large N ticks without drift. |
| TC-WU-05 | U | Multiple due messages in one tick: all are attempted (concurrent); final states consistent (no double terminal). | Many messages due at once. |
| TC-WU-06 | U | Post-success / post-terminal-failed: message **not** in due structure. | Remove from heap on transition. |
| TC-WU-07 | I | After worker restart, due set matches persisted `nextDueAt` for **owned** pendings only. | Mix owned + skipped foreign shard in store (foreign skipped). |

---

## 4) Persistence keys and moves

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-PV-01 | U / I | Pending key path: `state/pending/shard-<shard_id>/<messageId>.json`. | `shard_id` zero-padding: **no** unless spec says so; use literal `shard-0`. |
| TC-PV-02 | U / I | Success key: `state/success/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json` matches clock at transition. | **DST / midnight** boundary: hour folder changes; document UTC vs local. |
| TC-PV-03 | U / I | Failed key: `state/failed/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json` same clock rules. | |
| TC-PV-04 | I | After success, pending object **not** authoritative (deleted or ignored by policy—**one** clear rule). | Listing pending prefix does not resurrect terminal. |
| TC-PV-05 | I | No duplicate **terminal** keys for same `messageId` on retry of persistence write (idempotent put or guarded). | Simulate client retry. |

---

## 5) newMessage / activation / API-first

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-NM-01 | I | `POST /messages` creates durable pending **before** worker attempts send. | Order: persist then activate in harness. |
| TC-NM-02 | U / I | Attempt **#1** at `attemptCount=0` runs with **0s** delay after valid activation. | |
| TC-NM-03 | I | Worker rejects or skips activation if pending missing / schema invalid (defined behavior). | Empty file, wrong JSON. |
| TC-NM-04 | E | Full flow: API → pending on correct shard → worker → mock SMS. | |

---

## 6) Idempotency and duplicates

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-ID-01 | U / I | Duplicate `newMessage` / activation for same `messageId`: **one** terminal outcome. | Double HTTP callback simulation. |
| TC-ID-02 | I | After **success** terminal, duplicate send attempt → **no** second success object / no pending resurrection. | |
| TC-ID-03 | I | After **failed** terminal, duplicate processing → **no** second failed object. | |
| TC-ID-04 | I | Concurrent ticks / double due scheduling: **one** terminal per `messageId`. | Same message in race. |
| TC-ID-05 | E | API duplicate `POST /messages` with same body: behavior per product rule (reject / idempotent **same** `messageId` / new id each time—**must be documented and tested**). | |

---

## 7) Bootstrap, resilience, malformed data

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-RQ-01 | I | Restart worker: all **owned** pendings reappear in scheduler with correct `nextDueAt`. | |
| TC-RQ-02 | I | Pending with **invalid JSON** → skipped, worker **starts**; metric/log if present. | Truncated file, `{}`, missing `messageId`. |
| TC-RQ-03 | I | Pending with **`attemptCount` > 6** or **negative** → skip or quarantine (defined behavior). | |
| TC-RQ-04 | I | Pending with `nextDueAt` **far past** → becomes due immediately on bootstrap. | |
| TC-RQ-05 | I | Transient persistence **read** failure during scan → **bounded backoff** retry; then success. | After N failures, degraded path if implemented (TC-RQ-06). |
| TC-RQ-06 | I | (Optional) Exceed max bootstrap retry threshold → worker signals **degraded** / does not silently drop shard. | |
| TC-RQ-07 | I | Local idempotency cache cleared or **rehydrated** from persistence on restart—stale cache cannot block recovery. | Kill after in-memory state diverges. |
| TC-RQ-08 | I | Terminal object exists in success/failed prefix; **no** matching pending processing resumes. | Orphan pending deleted on success—ensure no duplicate processing. |

---

## 8) REST API

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-API-01 | U / I | `POST /messages`: missing `to` or `body` → **4xx**. | Empty string vs whitespace—define. |
| TC-API-02 | U / I | `POST /messages`: wrong types (`to` number) → **4xx**. | |
| TC-API-03 | U / I | `POST /messages`: valid payload → **2xx** + `messageId` in response shape. | |
| TC-API-04 | U / I | `POST /messages/repeat?count=N`: **N > 0** integer → **N** distinct `messageId`s. | |
| TC-API-05 | U / I | `count = 0`, negative, non-integer, **exceeding cap** → **4xx**. | `count = MAX+1`. |
| TC-API-06 | U / I | `GET /messages/success` **no** `limit` → default **100** entries or fewer. | |
| TC-API-07 | U / I | `GET /messages/failed` same as TC-API-06. | |
| TC-API-08 | U / I | `limit=1`, `limit=max`, `limit` **too large** → per clamp/reject policy (**4xx** or cap). | |
| TC-API-09 | U / I | `limit=0`, negative, non-numeric → **4xx**. | |
| TC-API-10 | U / I | `GET /healthz` → **2xx**, fast. | |
| TC-API-11 | U / I | Error responses include **stable** JSON shape (`code`, `message`). | |
| TC-API-12 | I | `POST /messages` does **not** invoke broad S3 list for unrelated prefixes. | Spy persistence layer. |

---

## 9) Recent outcomes cache

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-CA-01 | U | Capacity ≥ **max(limit)** supported (≥ **100**). | |
| TC-CA-02 | U | Eviction: adding item 101 drops oldest per policy (FIFO). | **Per-stream** vs **global**—test chosen design. |
| TC-CA-03 | U | Success terminal updates **success** view; **failed** terminal updates **failed** view. | No cross-contamination. |
| TC-CA-04 | U | `GET /messages/success` with `limit` **less than** cache size returns correct slice (most recent first). | |
| TC-CA-05 | U | Empty cache → empty list / **200** with `[]`. | |
| TC-CA-06 | U / I | Read path: **zero** S3 list-objects for outcomes endpoints. | Spy. |

---

## 10) Mock SMS provider

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-SMS-01 | U / I | Valid `to`+`body` → **2xx** when trial succeeds. | |
| TC-SMS-02 | U / I | Missing `to`/`body` to mock → **4xx** (bad request to mock). | Not send-outcome path. |
| TC-SMS-03 | U / I | `shouldFail=true` → always **5xx** (never **2xx**). | |
| TC-SMS-04 | U / I | Intermittent mode: with `RNG_SEED` fixed, sequence over K requests is **reproducible**. | |
| TC-SMS-05 | U / I | **`503`** vs **`500`/`502`** both exercised when `UNAVAILABLE_FRACTION` mixed. | Worker still retries both. |
| TC-SMS-06 | U | Mock **4xx** on send path must **not** occur for syntactically valid simulate request (only validation errors). | |
| TC-SMS-07 | I | Optional `LATENCY_MS` > 0 delays response without changing outcome logic. | Worker still completes. |

---

## 11) Worker ↔ mock SMS integration

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-WS-01 | I | Worker **POST** includes `to`, `body` from pending payload; optional `messageId` if implemented. | |
| TC-WS-02 | I | **Timeout** or connection error to mock (if implemented) treated as failed send / retry. | **Edge:** define behavior. |
| TC-WS-03 | I | Mock returns **599** or **501**—still non-2xx success → failed send if worker maps all **5xx** as retry. | Align with **any 5xx** rule. |
| TC-WS-04 | I | Mock returns **204** → success. | 2xx edge. |

---

## 12) End-to-end scenarios

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-E2E-01 | E | Happy path: SMS **2xx** first try → success key + recent cache. | |
| TC-E2E-02 | E | Retry then success: SMS **5xx** then **2xx** → pending updates then success. | |
| TC-E2E-03 | E | All attempts **5xx** → terminal **failed** after threshold. | |
| TC-E2E-04 | E | Mid-retry **restart** worker → retry completes correctly. | |
| TC-E2E-05 | E | `POST /messages/repeat?count=100` under cap → 100 pendings processed (smoke). | Reduce if CI slow. |
| TC-E2E-06 | E | Pagination/query: `GET .../success?limit=10` after 20 successes → 10 items. | |

---

## 13) Scaling / ownership change (lightweight)

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-SC-01 | I | Change **only** `pod_index` in harness: worker processes **new** owned shard set; **ignores** former shards. | Optional multi-instance fake. |
| TC-SC-02 | U / doc | `TOTAL_SHARDS` change: **migration** not covered in CI; document manual procedure. | See [`TESTS.md`](TESTS.md) §2. |

---

## 14) Observability (optional / smoke)

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-OB-01 | L | Lifecycle log line contains `messageId`, `shard_id`, `attemptCount` on state change. | Log capture in test optional. |
| TC-OB-02 | L | Bootstrap log contains owned range and scan counts. | |

*(Layer **L** = log/metric assertion or manual checklist.)*

---

## 15) Traceability

When implementing, reference:

- Sharding: TC-SH-* ↔ [`SHARDING.md`](SHARDING.md)
- Lifecycle: TC-RT-*, TC-WU-*, TC-NM-* ↔ [`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md)
- Resilience: TC-RQ-* ↔ [`RESILIENCE.md`](RESILIENCE.md)
- REST / cache: TC-API-*, TC-CA-* ↔ [`REST_API.md`](REST_API.md)
- Mock: TC-SMS-* ↔ [`MOCK_SMS.md`](MOCK_SMS.md)

---

## 16) Summary counts (for planning)

- **Sharding:** 7 cases  
- **Retry / attempts:** 6  
- **Wakeup:** 7  
- **Persistence keys:** 5  
- **Activation:** 4  
- **Idempotency:** 5  
- **Resilience / bootstrap:** 8  
- **REST:** 12  
- **Cache:** 6  
- **Mock SMS:** 7  
- **Worker-SMS:** 4  
- **E2E:** 6  
- **Scaling:** 2  
- **Observability (optional):** 2  

**Total enumerated:** **81** test case rows (some combine U+I; adjust per test pyramid).
