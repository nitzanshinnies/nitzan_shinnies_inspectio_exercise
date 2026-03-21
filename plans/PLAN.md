# nitzan_shinnies_inspectio_exercise - General Plan

This document mirrors the architect’s “High-Throughput SMS Retry Scheduler” specification and defines the required system behaviors for the interview exercise.

## 1) System overview

- Build a distributed system that can handle tens-of-thousands of SMS messages per second.
- Use AWS S3 as the primary source of truth for persistence and crash resilience.
- Expose a REST API (Python/FastAPI) for message submission and for querying recent outcomes.
- Run the scheduler/worker logic inside a Kubernetes StatefulSet so each pod has stable identity for deterministic sharding.
- Run a **health monitor** container that can **reconcile mock SMS audit logs** with **S3** lifecycle state **on demand** via its **REST API** ([`plans/HEALTH_MONITOR.md`](HEALTH_MONITOR.md)).

## 2) Stack & runtime requirements

- Python 3.11+
- FastAPI
- `aioboto3` (async AWS operations)
- `uvicorn` to run the FastAPI service(s)
- **Redis** (outcomes hot cache; dedicated container); **`redis-py`** / **`redis.asyncio`** in the **notification service**

## 3) S3 data model & bucket layout

All message state is persisted in S3 under the following key prefixes:

- Pending (`<shard>` = folder segment `shard-<shard_id>`; see [`plans/SHARDING.md`](SHARDING.md)):
  - `state/pending/shard-<shard_id>/<messageId>.json`
- Success:
  - `state/success/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`
- Failed (terminal):
  - `state/failed/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`
- Outcome notifications (durable log for the **notification service**; see [`plans/NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md)):
  - `state/notifications/<yyyy>/<MM>/<dd>/<hh>/<notificationId>.json`

### UTC and date-partition segments (required)

For **`state/success/`**, **`state/failed/`**, and **`state/notifications/`**, the path segments **`<yyyy>`**, **`<MM>`**, **`<dd>`**, **`<hh>`** are derived from **UTC** (Coordinated Universal Time):

- Use the **instant** when the object is written (terminal transition time for success/failed; **`recordedAt`** / write time for notifications—see [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md)).
- **24-hour** hour field **`hh`** (**00**–**23**), zero-padded month/day/hour.
- All pods and services **must** use the same rule so keys are stable and the health monitor can list predictable prefixes.

**Epoch fields** (`nextDueAt`, `recordedAt`, mock audit `receivedAt_ms`, etc.) are **Unix epoch milliseconds** (UTC instant); they are **not** ambiguous with local timezones.

### JSON schema

The pending object (and the persisted payload it contains) follows this schema:

```json
{
  "messageId": "uuid-string",
  "attemptCount": 0,
  "nextDueAt": 1700000000,
  "status": "pending",
  "payload": { "to": "...", "body": "..." },
  "history": []
}
```

- `messageId`: UUID string
- `attemptCount`: integer in range `0..6` (attempt #1 corresponds to `attemptCount = 0`)
- `nextDueAt`: epoch milliseconds (UTC instant)
- `status`: see **`Pending status` vs key location** below
- `payload`: SMS input (`to`, `body`)
- `history`: optional timestamps/outcomes

#### Pending `status` vs S3 key location (required)

- Any object stored under **`state/pending/shard-<shard_id>/`** **must** have **`"status": "pending"`**. Do **not** persist `success` or `failed` in the JSON while the key remains under a pending prefix; that state is **invalid** (bootstrap should **skip/quarantine**—see [`TEST_LIST.md`](TEST_LIST.md) **TC-RQ-12**).
- When the message is **moved** to a terminal key, the object body **must** use **`"status": "success"`** or **`"status": "failed"`** to match the prefix (`state/success/...` vs `state/failed/...`).

## 4) Sharding & worker ownership (deterministic, no contention)

### Shard calculation

- `shard_id = hash(messageId) % TOTAL_SHARDS`

Use a deterministic hash function (e.g., `sha256`) so shard assignment is stable.

### Worker shard ownership

Workers run as a Kubernetes StatefulSet with stable pod identity such as `worker-0`, `worker-1`, etc.

- Each pod computes `pod_index` from the `HOSTNAME` environment variable.
- Each pod owns a contiguous shard range:
  - `range(pod_index * shards_per_pod, (pod_index + 1) * shards_per_pod)`

Contention avoidance requirement:

- Exactly one worker pod is responsible for the `state/pending/shard-<shard_id>/` prefix for any given `shard_id` (so only that pod reads/writes that prefix).

## 5) Core message lifecycle & retry timeline

### newMessage hook (requirements)

Upon activation for a given message:

1. **Idempotency check**
   - Verify whether `messageId` already exists in the local cache or in S3.
2. **Initial persistence**
   - Persist the message under `state/pending/shard-<shard_id>/<messageId>.json`.
3. **Attempt #1**
   - Call `send(m)` immediately (0s delay).
4. **On failure**
   - Increment `attemptCount`
   - Calculate `nextDueAt` based on the retry timeline
   - Update the message in S3
   - Add the message to the in-memory scheduler so it will be retried at the correct time.

### wakeup loop cadence (requirements)

- Every worker must run a `wakeup()` loop with a cadence of **exactly every 500ms**.
- During each tick, select all messages where `nextDueAt <= now` and execute `send(m)` concurrently.

### State transitions in S3 (requirements)

- **Success**
  - Move the message representation from `state/pending/...` to `state/success/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`.
- **Failure and retries**
  - If `attemptCount < 6`:
    - Update S3 with the new `nextDueAt` and keep the message in the retry pipeline.
- **Terminal failure**
  - If `attemptCount == 6`:
    - Move the message to `state/failed/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json` and stop further retries.

### Retry timeline (architect-defined)

Use the following delay timeline relative to the previous attempt:

- #2: 0.5s
- #3: 2s
- #4: 4s
- #5: 8s
- #6: 16s

## 6) Crash resilience requirements

On startup, each worker pod must:

- Scan its assigned pending shard prefixes: `state/pending/shard-<X>/`
- Re-populate its in-memory scheduler from persisted `nextDueAt` values for all pending messages
- Continue processing without losing retry ordering.

## 7) REST API surface (requirements)

Implement the following endpoints:

1. `POST /messages`
   - Send a single message.
2. `POST /messages/repeat?count=N`
   - Load test endpoint: query **`count`**, JSON body same as **`POST /messages`**; body reused **`N`** times.
3. `GET /messages/success` (`limit` optional, default **100**; `to` optional—see [`plans/REST_API.md`](REST_API.md))
   - Return the most recent successful outcomes (via notification service + Redis).
4. `GET /messages/failed` (same `limit` / `to` rules as success)
   - Return the most recent failed outcomes (via notification service + Redis).
5. `GET /healthz`
   - Basic health endpoint(s).

Recent outcomes performance requirement:

- Do not list large `state/success/` or `state/failed/` prefixes to answer each `GET /messages/success` or `GET /messages/failed`.
- Use an **outcomes notification service** (dedicated container) plus **Redis** (dedicated container) for the **hot** recent-outcomes cache, and a durable **`state/notifications/...`** log in S3; on notification service startup **hydrate ~10,000** newest records from S3 **into Redis** (cold path only). **Details:** [`plans/NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md).

## 8) Mock SMS provider container (requirements)

**Detailed plan:** [`plans/MOCK_SMS.md`](MOCK_SMS.md) (intermittent/probabilistic failures, **send audit log / integrity validation**, **module-level behavior constants**, and validation checklist).

The mock SMS provider must be a separate container (single service) that **simulates** SMS sends for the worker and acts as the **integrity witness** for outbound attempts: it **records every handled `POST /send`** (structured **JSONL on stdout**, in-memory ring, optional **`GET /audit/sends`**) so **tests and production-like runs** (still using the mock) can **validate** that sends match the planned retry schedule—see [`plans/MOCK_SMS.md`](MOCK_SMS.md) §8. **No web UI** for tuning behavior; all tunable **behavior** parameters are **named constants in the mock’s Python module** (change by editing code / redeploy).

- Endpoint:
  - `POST /send`
- Request JSON:
  - `to`: string
  - `body`: string
  - `shouldFail`: optional boolean
  - `messageId`: optional string (worker **should** include for audit/integrity)
  - `attemptIndex`: optional int (e.g. `attemptCount` at send time; **recommended** for audit correlation—see `MOCK_SMS.md` §8)
- Failure behavior:
  - If `shouldFail=true`, the provider must always fail the request.
  - Otherwise, the provider must fail a fixed fraction of requests per the module’s **`FAILURE_RATE`** constant (so that some messages fail during load).
  - Simulated failures should reflect realistic categories: **failed to send** (e.g. invalid recipient, line error) vs **service unavailable** (transient outage); both are returned as **`5xx`** (see `MOCK_SMS.md`).
- Success/failure signal (send outcome):
  - Success → HTTP **`2xx`**.
  - Simulated send failure → HTTP **`5xx`** (not **`4xx`** on the normal send path; **`4xx`** reserved for bad requests to the mock).
- Optional simulated latency:
  - Governed by module constants (e.g. **`LATENCY_MS`**) per `MOCK_SMS.md`—not a separate admin UI.

## 9) Health monitor container (SMS audit vs S3)

**Detailed plan:** [`plans/HEALTH_MONITOR.md`](HEALTH_MONITOR.md).

A **dedicated health monitor** container **compares** the mock SMS send audit (via **`GET /audit/sends`** when a check runs; see [`plans/MOCK_SMS.md`](MOCK_SMS.md) §8) to **S3** (`state/pending/...`, `state/success/...`, `state/failed/...`) as the **source of truth**. **Full reconciliation runs only on demand** via a **REST `POST`** (suggested path **`POST /internal/v1/integrity-check`**—[`plans/HEALTH_MONITOR.md`](HEALTH_MONITOR.md) §4.2); **`GET /healthz`** is **liveness only** and does **not** trigger that work. It **must not** write lifecycle keys or sit on the worker hot path.

## 10) Testing plan (requirements-first)

**Detailed plan:** [`plans/TESTS.md`](TESTS.md) (unit/integration/e2e scope, tooling, determinism, traceability, checklist).

**Full test case list:** [`plans/TEST_LIST.md`](TEST_LIST.md) (numbered cases and edge cases).

**Strict TDD:** [`plans/TESTS.md`](TESTS.md) §1.1–§1.2 — tests assert planned behavior; stay red until implementation; a **tests-first branch** may add tests without implementing `src/` yet (see §1.2).

**Recent outcomes architecture:** [`plans/NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md) (notification service container + **Redis** container + S3 log + hydration into Redis).

Before meaningful implementation:

- Unit test requirements:
  - Shard assignment and worker shard range ownership mapping
  - `nextDueAt` computation for the architect’s retry timeline
  - Correct S3 state transitions: `pending -> success` and `pending -> failed`
  - Recent outcomes via **notification service + Redis** (bounded streams; default `limit` 100); see [`plans/NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md)
- Integration test requirements:
  - Simulate S3 using LocalStack or moto
  - End-to-end flow: API creates pending state → worker processes retries → terminal S3 keys → **worker publishes to notification service** → **Redis** updated → `GET /messages/success|failed` returns expected rows **without** broad terminal-prefix listing on each request
  - **Health monitor:** **`POST`** integrity-check reconciles **mock audit** vs **S3** lifecycle; **`GET /healthz`** is liveness-only ([`plans/HEALTH_MONITOR.md`](HEALTH_MONITOR.md))

## 11) Detailed plan documents (index)

All normative detail lives in these files; keep them **consistent** with this sectioned summary:

| Section / topic | Document |
|-----------------|----------|
| System context, components, local dev | [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) |
| Sharding, pending prefix, ownership | [`SHARDING.md`](SHARDING.md) |
| Lifecycle, retry, wakeup, worker ↔ mock SMS | [`CORE_LIFECYCLE.md`](CORE_LIFECYCLE.md) |
| Worker/bootstrap resilience | [`RESILIENCE.md`](RESILIENCE.md) |
| REST API, `GET` outcomes path | [`REST_API.md`](REST_API.md) |
| Recent outcomes: Redis + notification + S3 log | [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md) |
| Mock SMS provider | [`MOCK_SMS.md`](MOCK_SMS.md) |
| Local file-backed mock S3 (`PersistencePort`) | [`LOCAL_S3.md`](LOCAL_S3.md) |
| Health monitor (mock audit vs S3) | [`HEALTH_MONITOR.md`](HEALTH_MONITOR.md) |
| Testing strategy | [`TESTS.md`](TESTS.md) |
| Enumerated test cases | [`TEST_LIST.md`](TEST_LIST.md) |

