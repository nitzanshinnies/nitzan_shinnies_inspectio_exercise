# TEST_LIST.md - Full enumerated test cases (Section 10.1)

Companion to [`plans/TESTS.md`](TESTS.md): a **concrete checklist** of test cases, including **edge cases**, for implementation and review. Each case should map to one or more automated tests (or a documented manual step).

**Legend:** **U** = unit, **I** = integration, **E** = end-to-end / multi-component, **L** = log/metric/manual.

**Revision:** expanded pass—**config/HTTP/cache/SMS boundary** edge cases, **atomicity**, **Unicode**, **cold start**, **misconfiguration**, and **cross-component** gaps.

---

## 1) Sharding and ownership

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-SH-01 | U | Same `messageId` and `TOTAL_SHARDS` always yields the same `shard_id`. | Vary process restart / re-import; hash must be stable. |
| TC-SH-02 | U | `shard_id` is always in `[0, TOTAL_SHARDS - 1]`. | `TOTAL_SHARDS = 1` (only shard 0). |
| TC-SH-03 | U | Changing `TOTAL_SHARDS` changes mapping (document as migration); **baseline** test uses fixed `TOTAL_SHARDS`. | **Optional:** same messageId maps to **different** shard when `TOTAL_SHARDS` differs. |
| TC-SH-04 | U | Owned range for `pod_index` P equals `range(P * spp, (P+1) * spp)` for given `shards_per_pod` (spp). | P = 0, **last** pod; max `shard_id` = `TOTAL_SHARDS - 1`. |
| TC-SH-05 | U | **Non-owner** processing path: message with `shard_id` outside owned set → **no** pending writes / skip. | Inject “foreign shard” pending in list simulation. |
| TC-SH-06 | U | `HOSTNAME` parsing → `pod_index` for `worker-0`, `worker-1`, realistic StatefulSet FQDN. | **Malformed** hostname (**empty**, garbage): **fail fast** vs default—**document + test**. |
| TC-SH-07 | I | Bootstrap list/list-prefix limited to **`state/pending/shard-<id>/`** for **owned** ids only. | No full-bucket scan. |
| TC-SH-08 | U | **Invalid topology:** `TOTAL_SHARDS <= 0` or `shards_per_pod <= 0` → **fail at startup** (or reject config). | |
| TC-SH-09 | U / doc | **`pod_count * shards_per_pod != TOTAL_SHARDS`:** uncovered shards vs overlap—**document** validation or enforce equality. | |
| TC-SH-10 | U | **messageId** edge: UUID per spec; **server-generated** path vs client—test **uniqueness** and **empty** rejection if applicable. | Path injection if id ever unsafe. |
| TC-SH-11 | U | Many `messageId`s in **same** `shard_id` bucket—correct processing order / no loss. | |
| TC-SH-12 | I | **Empty** owned pending prefix: bootstrap completes, scheduler empty, **no** error. | |
| TC-SH-13 | U | **Long / Unicode** `messageId` if allowed: key encoding stable; otherwise reject at API. | |

---

## 2) Retry timeline and `attemptCount`

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-RT-01 | U | After failure at **attempt #1** (`attemptCount=0`), `nextDueAt` = `now + 500ms`. | Injectable `now`. |
| TC-RT-02 | U | After failures **#2..#5**, delays **2s, 4s, 8s, 16s** from **failed attempt completion** time. | Table-driven goldens. |
| TC-RT-03 | U | After **6th failed attempt** (`attemptCount == 6`), **terminal failed**—no seventh schedule. | **Off-by-one** vs `CORE_LIFECYCLE` diagram. |
| TC-RT-04 | U | While `attemptCount < 6`, pending updated **in place** with monotonic `attemptCount` + new `nextDueAt`. | |
| TC-RT-05 | U | Success with `attemptCount in {0..5}` → **success** terminal; **no** spurious increment. | First-try vs last-retry-before-terminal. |
| TC-RT-06 | U | Valid writes: `attemptCount` in **0..6** only; corrupt → TC-RQ-* . | |
| TC-RT-07 | U | `nextDueAt` as **integer epoch ms**—no float/timezone ambiguity in storage. | |
| TC-RT-08 | U | `status` in JSON vs actual location inconsistent → recovery **skip/quarantine** (TC-RQ-12). | |
| TC-RT-09 | U | `history[]` append **if** implemented; **max length** or unbounded—document + test. | |
| TC-RT-10 | U | **Single outcome** per attempt: timeout vs late 5xx does **not** double-increment `attemptCount`. | Race window defined. |

---

## 3) Wakeup loop and due selection

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-WU-01 | U | At tick `T`, only `nextDueAt <= T` eligible. | **Inclusive** `== T`. |
| TC-WU-02 | U | `nextDueAt > T` → **not** sent this tick. | e.g. `T + 1ms`. |
| TC-WU-03 | U | Order: **non-decreasing `nextDueAt`**; tie-break **deterministic** (e.g. `messageId`). | **Many** ties. |
| TC-WU-04 | U | **500ms cadence:** ticks × 500ms = elapsed (modulo **first-tick** policy—document). | |
| TC-WU-05 | U | Many due in one tick: **concurrent** sends; **one** terminal per `messageId`. | **Zero** due; **hundreds** due. |
| TC-WU-06 | U | After success/terminal-failed: **removed** from due structure. | Safe if transition retried. |
| TC-WU-07 | I | Restart: due set = persisted `nextDueAt` for **owned** pendings. | Foreign shard in store **skipped**. |
| TC-WU-08 | U | **No due** messages: tick **no-ops** without SMS spam. | |
| TC-WU-09 | U | Message due only after **N** ticks—**never** early send. | |
| TC-WU-10 | I | **Bootstrap** completes (or gates sends) **before** tick processing—no orphan sends. | |
| TC-WU-11 | U | **Clock jump forward:** backlog drains **without** duplicate terminals (idempotent). | |
| TC-WU-12 | U | **Clock jump backward:** behavior defined (messages become “not yet due” again). | |

---

## 4) Persistence keys and moves

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-PV-01 | U / I | Pending: `state/pending/shard-<shard_id>/<messageId>.json`. | `shard-0`, `shard-10`. |
| TC-PV-02 | U / I | Success: `state/success/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json` per clock at transition. | Segments **UTC** ([`PLAN.md`](PLAN.md) §3); **midnight**, **year/month rollover**, **hh** 00–23. |
| TC-PV-03 | U / I | Failed: same partition rule as success. | **UTC** only. |
| TC-PV-04 | I | After success: pending **gone or ignored**—single source of truth. | |
| TC-PV-05 | I | **Idempotent** terminal write on client retry. | |
| TC-PV-06 | I | **Partial failure** (terminal written, pending delete fails or vice versa): **recovery** converges to one state. | Order of operations documented. |
| TC-PV-07 | I | **Concurrent** read during move: never two authoritative pendings for same logical message. | |
| TC-PV-08 | U | Filename `messageId` matches JSON `messageId`; else **skip** on bootstrap. | |
| TC-PV-09 | I | Prefix **list** never becomes unscoped full-bucket scan. | |

---

## 5) newMessage / activation / API-first

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-NM-01 | I | `POST /messages` **durably** pending **before** worker send. | Harness ordering. |
| TC-NM-02 | U / I | Attempt **#1** at `attemptCount=0`, **0s** delay after activation. | |
| TC-NM-03 | I | Missing/invalid pending → worker **skip/error** (defined). | Empty file, `{}`, wrong types. |
| TC-NM-04 | E | API → correct shard pending → worker → mock SMS. | |
| TC-NM-05 | U / I | **`Content-Type`** missing/wrong → **4xx** where applicable. | |
| TC-NM-06 | U / I | **Unknown JSON fields** → ignore vs **400** per policy. | |
| TC-NM-07 | U / I | **Oversized** body/request → **413**/4xx or limit—document. | |
| TC-NM-08 | I | `POST /messages/repeat?count=1` behaves like single create. | |
| TC-NM-09 | I | Worker **does not** create pending if API never did. | |

---

## 6) Idempotency and duplicates

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-ID-01 | U / I | Duplicate activation for same `messageId` → **one** terminal outcome. | |
| TC-ID-02 | I | After **success** terminal, replay → **no** second success key / no pending. | |
| TC-ID-03 | I | After **failed** terminal, replay → **no** second failed key. | |
| TC-ID-04 | I | **Concurrent** ticks on same message → **one** terminal. | |
| TC-ID-05 | E | Duplicate `POST /messages` same body: **documented** dedupe/new-id/reject behavior. | |
| TC-ID-06 | I | **Two workers / mis-routed** shard (simulated): only **owner** advances state; non-owner **no-ops**. | Complements TC-SH-05. |
| TC-ID-07 | I | **CAS / ETag** on pending update if used—lost update does not drop retries. | Optional pattern. |

---

## 7) Bootstrap, resilience, malformed data

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-RQ-01 | I | Restart: owned pendings restore with correct `nextDueAt`. | |
| TC-RQ-02 | I | **Invalid JSON** pending → skip; worker **starts**. | Truncated, `null` body. |
| TC-RQ-03 | I | `attemptCount` **> 6** or **< 0** → skip/quarantine. | |
| TC-RQ-04 | I | `nextDueAt` **far past** → **due immediately** after bootstrap. | |
| TC-RQ-05 | I | Transient read error during scan → **bounded backoff**, then success. | |
| TC-RQ-06 | I | (Optional) Too many bootstrap failures → **degraded** signal. | |
| TC-RQ-07 | I | **Idempotency cache** rehydrated/cleared on restart—no stale block. | |
| TC-RQ-08 | I | Terminal exists; **no** duplicate processing from orphan pending. | |
| TC-RQ-09 | I | **Duplicate** object keys same `messageId` in prefix (last-write-wins or error)—document. | |
| TC-RQ-10 | I | **Missing** `nextDueAt` / **null** in JSON → skip. | |
| TC-RQ-11 | I | **Empty** prefix + **multiple** owned shards: all scanned, **order-independent** correctness. | |
| TC-RQ-12 | I | `status: success` in file still under **pending** prefix → **skip** or repair. | |
| TC-RQ-13 | I | **Partial file** (crash mid-write) → skip / CRC if implemented. | |

---

## 8) REST API

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-API-01 | U / I | Missing `to` or `body` → **4xx**. | **Whitespace-only** string—define. |
| TC-API-02 | U / I | Wrong types for fields → **4xx**. | |
| TC-API-03 | U / I | Valid `POST /messages` → **2xx** + stable response shape incl. `messageId`. | |
| TC-API-04 | U / I | `repeat?count=N`, N≥1 integer → **N** distinct ids. | |
| TC-API-05 | U / I | `count` 0, negative, float, **> cap** → **4xx**. | |
| TC-API-06 | U / I | `GET /messages/success` no `limit` → default **100** (or less if fewer items). | |
| TC-API-07 | U / I | `GET /messages/failed` same as TC-API-06. | |
| TC-API-08 | U / I | `limit` = 1, max allowed, **above max** → clamp vs **4xx** per policy. | |
| TC-API-09 | U / I | `limit` 0, negative, `10.5`, non-numeric → **4xx**. | |
| TC-API-10 | U / I | `GET /healthz` → **2xx**, fast. | |
| TC-API-11 | U / I | Error JSON: **machine-readable** `code` + `message`. | |
| TC-API-12 | I | `POST /messages` **no** broad unrelated S3 **list**. | Spy. |
| TC-API-13 | U / I | **Unknown query** params → ignore vs **400** per policy. | |
| TC-API-14 | U / I | Wrong HTTP method on route → **405**/404 per framework. | |
| TC-API-15 | U / I | `repeat` **missing** `count` → **4xx**. | |
| TC-API-16 | U / I | **Unicode** / emoji in `to` and `body` round-trip (UTF-8). | |
| TC-API-17 | U / I | **`Accept`** / **Accept-Encoding** ignored or honored—no crash. | |
| TC-API-18 | I | **Concurrent** `POST /messages` (stress): no 5xx from trivial races; correct distinct ids. | Optional load smoke. |

---

## 9) Recent outcomes cache

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-CA-01 | U | Capacity ≥ **max(limit)** (≥ **100** default policy). | |
| TC-CA-02 | U | Eviction: overflow drops **oldest** per **FIFO**/LRU policy—test chosen design. | |
| TC-CA-03 | U | Success vs **failed** streams **isolated**—no wrong endpoint data. | |
| TC-CA-04 | U | `limit` < cache size → **most recent first**, length = `limit`. | |
| TC-CA-05 | U | Empty cache → **200** + `[]`. | |
| TC-CA-06 | U / I | No S3 **list** on GET outcomes—spy. | |
| TC-CA-07 | U | `limit` **> current cache length** → return **all** available (≤ limit). | |
| TC-CA-08 | U | **Same** `messageId` should not appear twice in one response unless spec allows—normally **dedupe** or impossible. | |
| TC-CA-09 | I | **API restart** alone: Redis + notification service still hold data; **GET** still works. **Full stack restart** (Redis empty): **hydration** repopulates from S3—assert behavior. | |
| TC-CA-10 | I | **Ordering**: outcome appended **when** terminal write committed (worker vs API path—document). | |

---

## 10) Mock SMS provider

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-SMS-01 | U / I | Valid body → **2xx** when trial succeeds. | |
| TC-SMS-02 | U / I | Missing `to`/`body` → **4xx** on mock. | |
| TC-SMS-03 | U / I | `shouldFail=true` → **always 5xx**. | |
| TC-SMS-04 | U / I | Fixed **`RNG_SEED`** → reproducible sequence. | |
| TC-SMS-05 | U / I | **`503`** and **`500`/`502`** both occur when `UNAVAILABLE_FRACTION` mixed. | |
| TC-SMS-06 | U | Valid simulate request → **never** **4xx** on “send outcome” path. | |
| TC-SMS-07 | I | `LATENCY_MS` > 0 delays only. | |
| TC-SMS-08 | U | **`FAILURE_RATE = 0`** → always **2xx** (except `shouldFail`). | |
| TC-SMS-09 | U | **`FAILURE_RATE = 1`** → always **5xx** (unless `shouldFail` override unnecessary). | |
| TC-SMS-10 | U | **`UNAVAILABLE_FRACTION` ∈ {0,1}`** → only one failure **family** used. | |
| TC-SMS-11 | I | **Concurrent** `POST /send` to mock—**thread-safe** RNG / no crashes. | |
| TC-SMS-12 | U / I | **Integrity audit:** each handled `POST /send` appears in **stdout JSONL** and in **`GET /audit/sends`** (when `EXPOSE_AUDIT_ENDPOINT`); fields include `http_status` / `outcome_kind`; optional **`attemptIndex`** round-trips. | |

---

## 11) Worker ↔ mock SMS integration

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-WS-01 | I | Request includes `to`, `body`; **`messageId`** and **`attemptIndex`** per integrity guidance ([`MOCK_SMS.md`](MOCK_SMS.md) §8). | |
| TC-WS-02 | I | **Timeout** / **connection refused** → failed send / retry. | |
| TC-WS-03 | I | **5xx** variants **501, 599** → retry per **any 5xx** rule. | |
| TC-WS-04 | I | **204 No Content** → success. | |
| TC-WS-05 | I | **300 redirect** (302) to worker client—define follow or treat as failure. | |
| TC-WS-06 | I | **2xx** with error text in body—still **success** if status 2xx. | |
| TC-WS-07 | I | **429** / **408** from mock—define retry vs treat as failure (spec: mock uses **5xx** for simulate fail; extra codes **optional** test). | |

---

## 12) End-to-end scenarios

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-E2E-01 | E | Happy path: SMS **2xx** → success key + cache. | |
| TC-E2E-02 | E | Retry then success. | |
| TC-E2E-03 | E | All **5xx** → terminal failed. | |
| TC-E2E-04 | E | Mid-retry **worker restart** → completes. | |
| TC-E2E-05 | E | `repeat` smoke (e.g. N=10 or 100 per CI budget). | |
| TC-E2E-06 | E | `GET .../success?limit=10` after 20 outcomes → 10 rows. | |
| TC-E2E-07 | E | **API only** (worker stopped): pending **remains**; no phantom success._timeout optional. | |
| TC-E2E-08 | E | **SMS down** then up: messages eventually succeed or terminal-fail per timeline. | |
| TC-E2E-09 | E | **`shouldFail: true`** on payload (if wired) forces failure path every time until terminal. | |
| TC-E2E-10 | E | **Mock audit vs lifecycle:** after a deterministic scenario, **mock send log** (`GET /audit/sends` or **stdout JSONL**) matches expected **attempt count / order** per `messageId` ([`MOCK_SMS.md`](MOCK_SMS.md) §8). | |

---

## 13) Scaling / ownership change (lightweight)

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-SC-01 | I | Change harness `pod_index`: **new** shard set only. | |
| TC-SC-02 | U / doc | `TOTAL_SHARDS` migration—**manual** procedure only. | |
| TC-SC-03 | doc | **Zero** worker replicas—no processing; document ops expectation. | |
| TC-SC-04 | doc | **Duplicate** `HOSTNAME`/ordinal misconfig—detect if possible. | |

---

## 14) Observability (optional / smoke)

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-OB-01 | L | Lifecycle fields: `messageId`, `shard_id`, `attemptCount`, transitions. | |
| TC-OB-02 | L | Bootstrap: hostname, owned range, scanned counts, invalid skipped. | |
| TC-OB-03 | L | **Out-of-range skip** increments diagnostic metric (`SHARDING` §4). | |

---

## 15) Security / abuse (lightweight)

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-SE-01 | U / I | **No** secrets / internal stack traces in API error JSON. | [`REST_API.md`](REST_API.md) §7. |
| TC-SE-02 | I | **Rate limiting** if implemented; **not** required by baseline spec. | |

---

## 16) Traceability

When implementing, map cases to spec checklists:

- **Sharding:** TC-SH-* ↔ [`SHARDING.md`](SHARDING.md) §8
- **Lifecycle:** TC-RT-*, TC-WU-*, TC-NM-* ↔ [`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md) §8
- **Resilience:** TC-RQ-* ↔ [`RESILIENCE.md`](RESILIENCE.md) §8
- **REST / outcomes:** TC-API-*, TC-CA-*, TC-NTF-* ↔ [`REST_API.md`](REST_API.md) §8, [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md) §10
- **Mock:** TC-SMS-* ↔ [`MOCK_SMS.md`](MOCK_SMS.md) §11
- **Health monitor:** TC-HM-* ↔ [`HEALTH_MONITOR.md`](HEALTH_MONITOR.md) §7
- **Security notes:** TC-SE-* ↔ [`REST_API.md`](REST_API.md) §7

---

## 17) Health monitor (mock audit vs S3)

| ID | Layer | Test case | Edge / notes |
|----|-------|-----------|--------------|
| TC-HM-01 | U | **Reconciliation logic:** fixture S3 terminal **success** + audit with **≥1** matching **`2xx`** for `messageId` → **pass**; missing **2xx** → **fail**. | [`HEALTH_MONITOR.md`](HEALTH_MONITOR.md) §3.3 |
| TC-HM-02 | U | **Terminal failed** vs audit: persisted **`attemptCount == 6`** and audit rows match documented rule (strict mode if **`attemptIndex`** present). | [`HEALTH_MONITOR.md`](HEALTH_MONITOR.md) §3.3–3.4 |
| TC-HM-03 | I | **`GET /healthz`** on monitor → **2xx** (liveness) **without** requiring a prior integrity run. | No full S3/mock scan |
| TC-HM-04 | I | **`POST` integrity-check** after happy-path E2E slice → **2xx** + body `ok` (or equivalent per [`HEALTH_MONITOR.md`](HEALTH_MONITOR.md) §4.2). | Compose or harness |
| TC-HM-05 | I | **Induced drift** then **`POST` integrity-check** → **503** / **422** or violation JSON (not **2xx** `ok`). | Fail-closed default |

---

## 18) Summary counts (for planning)

| Section | Count |
|---------|-------|
| 1 Sharding | 13 |
| 2 Retry / attempts | 10 |
| 3 Wakeup | 12 |
| 4 Persistence keys | 9 |
| 5 Activation / API-first | 9 |
| 6 Idempotency | 7 |
| 7 Bootstrap / malformed | 13 |
| 8 REST | 18 |
| 9 Cache | 10 |
| 10 Mock SMS | 12 |
| 11 Worker↔SMS | 7 |
| 12 E2E | 10 |
| 13 Scaling | 4 |
| 14 Observability | 3 |
| 15 Security | 2 |
| 17 Health monitor | 5 |

**Total enumerated:** **134** test case rows (some U+I overlap; adjust per pyramid).

---

## 19) Resolved architecture: outcomes notification service + Redis

**Spec:** [`plans/NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md). Workers **publish** after durable terminal S3 writes; a **notification service** (dedicated container) writes **`state/notifications/...`** and updates **Redis** (dedicated container); the **REST API** queries the notification service only. On startup the notification service **hydrates ~10k** newest records from S3 **into Redis**.

### 19.1 Integration tests (normative)

| ID | Layer | Test case | Notes |
|----|-------|-----------|-------|
| TC-NTF-01 | I | Worker completes terminal **success** in S3 → **publish** → `GET /messages/success` returns that `messageId` **without** listing `state/success/`. | Spy persistence `list` on API `GET`. |
| TC-NTF-02 | I | Same for **failed** terminal and `GET /messages/failed`. | |
| TC-NTF-03 | I | **Order:** if publish is stubbed to fail, S3 terminal still exists; retry publish succeeds → GET reflects outcome. | |
| TC-NTF-04 | I | **Notification service restart:** after terminal events persisted to `state/notifications/...`, restart service (Redis **empty** or flushed) → hydration fills **Redis** → **GET** returns recent rows up to **`HYDRATION_MAX`**. | |
| TC-NTF-07 | I | **Redis unavailable:** notification service **readiness** / publish behavior per [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md) §7; API outcomes **503** or degraded—**document + test**. | |
| TC-NTF-05 | U / I | **Dedupe / idempotency:** duplicate publish same `messageId`+outcome does **not** corrupt GET ordering per documented policy ([`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md) §4). | |
| TC-NTF-06 | I | **`HYDRATION_MAX` boundary:** with >10k notifications in S3, **Redis** holds **at most** cap after hydration; **newest** bias preserved. | |

### 19.2 Remaining implementation choices (test when decided)

| Topic | Suggested test |
|-------|----------------|
| **“Promptly”** after publish | **I:** bound latency (same process vs HTTP hop)—document. |
| **Readiness vs `GET /healthz`** | [`REST_API.md`](REST_API.md) §3.5—**I:** readiness includes notification service dependency if split-process. |

### 19.3 Persistence layer (contract tests)

| Gap | Suggested coverage |
|-----|-------------------|
| **Dedicated persistence service surface** | Matrix over **put / get / delete / list-prefix** (owned paths only), **error mapping**, and **async** cancellation behavior if using `aioboto3`. |
| **Strong vs eventual consistency** | **moto/file-backend:** usually strong. **Real S3** optional stage: put + immediate get/list visibility. |

### 19.4 Lifecycle / ops edge cases (optional depth)

| Gap | Suggested coverage |
|-----|-------------------|
| **Graceful shutdown (SIGTERM)** | Worker finishes current tick or cancels tasks cleanly; **no** stuck pendings except those mid-retry per rules; optional **pytest** “no pending asyncio tasks” after shutdown hook. |
| **In-flight send when SIGTERM** | Define: still count attempt outcome vs discard—**test matches policy**. |
| **SOAK / memory** | Long run of 500ms loop + many messages: RSS stable (optional, not CI-gated). |

### 19.5 Test methodology (not duplicate case IDs)

| Gap | Note |
|-----|------|
| **Property-based / fuzz** | `hypothesis` for `nextDueAt` recurrence, shard id range, JSON parse robustness. |
| **Contract / OpenAPI** | If schema published, **schemathesis** or Dredd against running API. |
| **Multi-container E2E** | **docker-compose** (API + worker + mock SMS + **health monitor** + LocalStack/Redis/notification as needed) optional; **in-process** tests remain baseline per [`TESTS.md`](TESTS.md). |

### 19.6 Explicit non-goals (no test required unless you extend spec)

- Multi-region S3, IAM least-privilege proofs, KMS, per-tenant isolation, cost budgets, mobile clients/CORS, chaos in production.

---

### Coverage confidence

With **§19** below resolved via [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md), **§19** tracks **recent-outcomes** behavior. **§17** (TC-HM-*) + [`HEALTH_MONITOR.md`](HEALTH_MONITOR.md) cover **mock-audit vs S3** integrity. Together these align with [`PLAN.md`](PLAN.md), [`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md), [`SHARDING.md`](SHARDING.md), [`RESILIENCE.md`](RESILIENCE.md), [`REST_API.md`](REST_API.md), and [`MOCK_SMS.md`](MOCK_SMS.md). Remaining work is **operational depth** (§19.4–19.5) and **extended** security/scale (§15, §13).
