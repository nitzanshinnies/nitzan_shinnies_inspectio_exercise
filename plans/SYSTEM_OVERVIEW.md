# SYSTEM_OVERVIEW.md - Detailed System Overview (Requirements-Level)

This document expands the architect’s *High-Throughput SMS Retry Scheduler* specification into a detailed, requirements-level system overview for the interview exercise.

## 1) High-level architecture

The system is composed of logical services/services-with-containers:

1. **Backend / REST API service** (Python, FastAPI, run with `uvicorn`)
   - Exposes the REST endpoints required by the architect.
   - Creates the durable pending message state in S3 (through the dedicated persistence service).
   - Serves `GET /messages/success` and `GET /messages/failed` by **querying the notification service** (not by listing `state/success/` or `state/failed/` on each request).
   - Triggers the worker “newMessage” flow for attempt #1 (0s delay).

2. **Worker scheduler** (Kubernetes StatefulSet; pods `worker-0`, `worker-1`, …)
   - Provides deterministic sharding by claiming an exclusive contiguous shard range in S3 based on `HOSTNAME` (`pod_index`) and configured `shards_per_pod`.
   - Bootstraps on startup by scanning the worker-owned pending shards in S3 and reconstructing the due-work view from persisted `nextDueAt`.
   - Runs a wakeup loop with a cadence of **exactly every 500ms** (same as [`plans/PLAN.md`](PLAN.md) §5).
   - Executes due message sends concurrently within each tick and applies the exact retry timeline transitions.

3. **Dedicated S3 persistence service (required boundary)**
   - All S3 reads/writes from **API and workers** MUST go through this service (they do not talk to S3 directly).
   - **Exception (read-only):** the **health monitor** may use the persistence service’s **read** API or a **read-only** direct S3 client for lifecycle prefixes only—see [`HEALTH_MONITOR.md`](HEALTH_MONITOR.md) §2.2.
   - **AWS mode**: uses `aioboto3` for async S3 operations.
   - **Local dev mode**: uses an in-process mock S3 implementation that performs file reader/writer semantics on a local directory while presenting the same persistence interface — **detailed spec and tests:** [`plans/LOCAL_S3.md`](LOCAL_S3.md).

4. **Redis (dedicated container — outcomes hot cache)**
   - Runs as its **own container** (e.g. official Redis image).
   - Holds **bounded** recent-outcome structures for **success** and **failed** streams (**LIST**/ZSET pattern—see [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md) §4).
   - Accessed **only** by the **notification service** (not directly by the REST API or workers).

5. **Outcomes notification service (dedicated container)**
   - Accepts **publish** requests from workers after terminal S3 writes.
   - Writes the **durable** log to `state/notifications/...` in S3 (via persistence service) and **updates Redis**.
   - Exposes **query** endpoints (or internal HTTP) used by the **REST API** for `GET /messages/success` and `GET /messages/failed`.
   - On startup, **hydrates Redis** from S3 with up to **`HYDRATION_MAX`** records (default **10,000**), walking **recent hour prefixes** backward (acceptable **cold-start** listing; not per user request).
   - **Detailed plan:** [`plans/NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md).

6. **Mock SMS provider (separate single container)**
   - Exposes `POST /send`.
   - Fails some requests to exercise retry behavior (including a request-controlled `shouldFail` switch).
   - Maintains a **send audit** (stdout JSONL + **`GET /audit/sends`**) per [`MOCK_SMS.md`](MOCK_SMS.md) §8.

7. **Health monitor (separate single container)**
   - **On demand:** a **`POST`** endpoint runs **one** reconciliation—**fetches** mock SMS **audit** and **reads** S3 lifecycle keys (`pending` / `success` / `failed`) to compare “what the mock saw” vs “what S3 says.”
   - **`GET /healthz`:** **liveness only** (no full audit/S3 scan on each probe).
   - **Read-only** toward lifecycle state; **not** on the worker hot path.
   - **Detailed plan:** [`plans/HEALTH_MONITOR.md`](HEALTH_MONITOR.md).

## 2) Persistence interface & required S3 key layout

### 2.1 Persistence keys (required)

All message state is persisted in S3 under the architect-required prefixes:

- **Pending** (canonical folder segment: **`shard-<shard_id>`**; see [`SHARDING.md`](SHARDING.md))
  - `state/pending/shard-<shard_id>/<messageId>.json`
- **Success**
  - `state/success/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`
- **Failed (terminal)**
  - `state/failed/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`
- **Outcome notifications (durable log for recent-outcomes service)**
  - `state/notifications/<yyyy>/<MM>/<dd>/<hh>/<notificationId>.json`

**Date partitions (`yyyy` / `MM` / `dd` / `hh`):** **UTC**, 24-hour **`hh`**, zero-padded—same instant semantics as [`PLAN.md`](PLAN.md) §3 (terminal write time or notification **`recordedAt`**).

### 2.2 Pending JSON schema (required)

The persisted pending object follows:

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

Field constraints:
- `attemptCount`: integer in range `0..6` (attempt #1 corresponds to `attemptCount = 0`)
- `nextDueAt`: epoch milliseconds (UTC instant)
- `status`: while the object lives under **`state/pending/shard-*/`**, **must** be **`pending`**. Terminal objects under **`state/success/...`** or **`state/failed/...`** **must** use **`success`** or **`failed`** respectively ([`PLAN.md`](PLAN.md) §3).
- `payload`: `{ "to": "...", "body": "..." }`
- `history`: optional array (timestamps/outcomes)

### 2.3 “Move” semantics (required)

When transitioning a message:
- On success: the message representation must move from `state/pending/...` to `state/success/...`.
- On terminal failure: the message representation must move from `state/pending/...` to `state/failed/...`.

After the terminal transition, the message must no longer be eligible from the pending prefix.

## 3) Sharding, ownership, and crash resilience (required)

### 3.1 Shard assignment (required)

Shard calculation:
- `shard_id = hash(messageId) % TOTAL_SHARDS`

Use a deterministic hash function (e.g., sha256) so shard assignment is stable.

### 3.2 Worker shard ownership (required; no contention)

StatefulSet pods must deterministically own an exclusive contiguous shard range:
- Derive `pod_index` from the `HOSTNAME` environment variable.
- Each pod owns:
  - `range(pod_index * shards_per_pod, (pod_index + 1) * shards_per_pod)`

Contention avoidance requirement:
- Exactly one worker pod is responsible for reading/writing `state/pending/shard-<shard_id>/` for any given `shard_id`.

### 3.3 Crash resilience bootstrap (required)

On startup, each worker pod must:
- Scan the worker-owned pending shards in S3:
  - `state/pending/shard-<shard_id>/`
- Re-populate its due-work view from persisted `nextDueAt` values for all pending messages it owns.
- Continue retry processing without losing retry ordering/eligibility.

## 4) Core message lifecycle and retry timeline (required)

### 4.1 newMessage hook activation (required)

When a message is activated for processing:

1. **Idempotency check**
   - Verify whether `messageId` already exists in the local cache or in S3 (via the persistence service).
2. **Ensure durable pending state**
   - The pending message must already be durably persisted in `state/pending/shard-<shard_id>/<messageId>.json` by the API.
   - The worker’s activation must validate the persisted pending state exists and is consistent for attempt #1 (attemptCount=0) before sending.
3. **Attempt #1**
   - Call `send(m)` immediately (0s delay).
4. **On failure**
   - Increment `attemptCount`.
   - Compute `nextDueAt` using the required timeline.
   - Update the pending object in S3.
   - Re-schedule the message in the worker’s due-work view.

### 4.2 Wakeup loop cadence and due selection (required)

The worker scheduler must:
- Run a wakeup loop with cadence **exactly every 500ms** (reliably meeting the 0.5s requirement).
- On each tick, select **all messages where `nextDueAt <= now`** for the worker-owned shards.
- Selection must be driven by a prioritized due-work structure ordered by `nextDueAt` (priority scheduling semantics), so that due messages are processed in a timely manner.

### 4.3 Concurrent sending within a tick (required)

During each tick, the system must execute `send(m)` **concurrently** for due messages (e.g., using `asyncio.gather` semantics) to reach high throughput.

### 4.4 Retry timeline and terminal failure (required)

After failure timeline:
- Attempt #2: +0.5s
- Attempt #3: +2s
- Attempt #4: +4s
- Attempt #5: +8s
- Attempt #6: +16s

Terminal failure:
- When `attemptCount == 6`, transition to `state/failed/...` and stop further retries.

## 5) REST API surface (required)

Implement:
- `POST /messages`
  - Send a single message.
- `POST /messages/repeat`
  - Load test endpoint: JSON body with **`count`** (optional **`to`** / **`body`**); create `N` copies.
- `GET /messages/success` (`limit` optional, default **100**; `to` optional—[`REST_API.md`](REST_API.md))
  - Return most recent successful outcomes (notification service → Redis).
- `GET /messages/failed` (same `limit` / `to` rules)
  - Return most recent failed outcomes (notification service → Redis).
- `GET /healthz`
  - Health endpoints.

Recent outcomes performance requirement:
- Avoid listing large `state/success/` / `state/failed/` trees on **each** `GET`.
- Serve `GET /messages/success` and `GET /messages/failed` via the **notification service**, which reads **Redis** (hot cache) with **S3 `state/notifications/...`** as durable log and **hydration** source—see [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md).

## 6) Mock SMS provider contract (required)

The mock SMS provider is a separate single container with:

- Endpoint: `POST /send`
- **Integrity:** records **every** handled send for validation (stdout **JSONL**, ring buffer, optional **`GET /audit/sends`**)—see [`MOCK_SMS.md`](MOCK_SMS.md) §8. Use this in **tests** and in **deployed** exercise stacks to verify **all outbound attempts** match expectations.
- Request JSON:
  - `to`: string
  - `body`: string
  - `shouldFail`: optional boolean
  - `messageId`: optional string (worker **should** set for audit)
  - `attemptIndex`: optional int (recommended; aligns audit with lifecycle)

Failure behavior:
- If `shouldFail=true`, always fail ( **`5xx`** send outcome).
- Otherwise, fail a fixed fraction of requests per **module-level constants** in the mock (e.g. `FAILURE_RATE`) so some messages fail during tests/load.
- Failure kind for intermittent/`shouldFail` **`5xx`**: **failed to send** vs **service unavailable** (both **`5xx`**; see `MOCK_SMS.md`).
- **No web UI** for mock behavior; tune constants in source and redeploy.

Failure signal (send outcome):
- Success → **`2xx`**; simulated send failure → **`5xx`**. **4xx** only for invalid requests to the mock.

Optional simulated latency:
- Governed by module constants (see `MOCK_SMS.md`).

## 7) Local development mapping (required)

- **Mock S3 provider**: in-process file reader/writer that implements the same persistence interface as the dedicated S3 persistence service — see [`plans/LOCAL_S3.md`](LOCAL_S3.md) (interface, on-disk layout, test plan).
- **Redis**: dedicated container with `REDIS_URL` wired into the **notification service** (see [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md) §12).
- **Notification service**: dedicated container (or local run) talking to Redis + persistence layer.
- **Mock SMS provider**: runs as a separate container (single container) calling `POST /send`.
- **Health monitor**: **specified** in [`PLAN.md`](PLAN.md) §1/§9 (include in compose/K8s for the exercise); `MOCK_SMS_URL` + read-only S3/persistence access; callers **`POST`** the integrity-check route to run **`GET /audit/sends`** + S3 compare ([`HEALTH_MONITOR.md`](HEALTH_MONITOR.md) §4).
- **State ownership**: worker pods still use `HOSTNAME` and shard-range ownership semantics so the same code paths apply in local and cluster environments.

## 8) Testing plan (requirements-first)

**Detailed plan:** [`plans/TESTS.md`](TESTS.md).

**Enumerated test cases:** [`plans/TEST_LIST.md`](TEST_LIST.md).

Before meaningful implementation:

- Unit tests should cover:
  - deterministic shard assignment and shard-range ownership mapping
  - wakeup due-selection behavior: only process messages with `nextDueAt <= now`
  - retry timeline mapping from `attemptCount` to `nextDueAt`
  - terminal transition correctness: `pending -> success` and `pending -> failed`
  - recent outcomes via **notification service + Redis** (no per-GET broad terminal-prefix listing)
- Integration tests should cover:
  - S3 persistence via local mock S3 and/or an AWS simulator
  - end-to-end: API creates pending → worker activation → retries → terminal S3 keys → **notification publish + Redis** → `GET` outcomes (see [`NOTIFICATION_SERVICE.md`](NOTIFICATION_SERVICE.md))
  - **Health monitor:** **`POST`** integrity-check reconciles mock audit vs S3; **`GET /healthz`** liveness only ([`HEALTH_MONITOR.md`](HEALTH_MONITOR.md) §4)

