# SYSTEM_OVERVIEW.md - Detailed System Overview (Requirements-Level)

This document expands the architect’s *High-Throughput SMS Retry Scheduler* specification into a detailed, requirements-level system overview for the interview exercise.

## 1) High-level architecture

The system is composed of logical services/services-with-containers:

1. **Backend / REST API service** (Python, FastAPI, run with `uvicorn`)
   - Exposes the REST endpoints required by the architect.
   - Creates the durable pending message state in S3 (through the dedicated persistence service).
   - Maintains/serves “recent outcomes” via a bounded cache to avoid S3 listing overhead.
   - Triggers the worker “newMessage” flow for attempt #1 (0s delay).

2. **Worker scheduler** (Kubernetes StatefulSet; pods `worker-0`, `worker-1`, …)
   - Provides deterministic sharding by claiming an exclusive contiguous shard range in S3 based on `HOSTNAME` (`pod_index`) and configured `shards_per_pod`.
   - Bootstraps on startup by scanning the worker-owned pending shards in S3 and reconstructing the due-work view from persisted `nextDueAt`.
   - Runs a wakeup loop with a cadence of ~500ms reliably.
   - Executes due message sends concurrently within each tick and applies the exact retry timeline transitions.

3. **Dedicated S3 persistence service (required boundary)**
   - All S3 reads/writes MUST go through this service (API and workers do not talk to S3 directly).
   - **AWS mode**: uses `aioboto3` for async S3 operations.
   - **Local dev mode**: uses an in-process mock S3 implementation that performs file reader/writer semantics on a local directory while presenting the same persistence interface.

4. **Mock SMS provider (separate single container)**
   - Exposes `POST /send`.
   - Fails some requests to exercise retry behavior (including a request-controlled `shouldFail` switch).

## 2) Persistence interface & required S3 key layout

### 2.1 Persistence keys (required)

All message state is persisted in S3 under the architect-required prefixes:

- **Pending**
  - `state/pending/<shard>/<messageId>.json`
- **Success**
  - `state/success/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`
- **Failed (terminal)**
  - `state/failed/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`

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
- `nextDueAt`: epoch milliseconds
- `status`: `pending | success | failed`
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
- Exactly one worker pod is responsible for reading/writing `state/pending/<shard>/` for any given `shard_id`.

### 3.3 Crash resilience bootstrap (required)

On startup, each worker pod must:
- Scan the worker-owned pending shards in S3:
  - `state/pending/<shard>/` (commonly expressed as `state/pending/shard-<X>/` in naming)
- Re-populate its due-work view from persisted `nextDueAt` values for all pending messages it owns.
- Continue retry processing without losing retry ordering/eligibility.

## 4) Core message lifecycle and retry timeline (required)

### 4.1 newMessage hook activation (required)

When a message is activated for processing:

1. **Idempotency check**
   - Verify whether `messageId` already exists in the local cache or in S3 (via the persistence service).
2. **Ensure durable pending state**
   - The pending message must already be durably persisted in `state/pending/<shard>/<messageId>.json` by the API.
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
- `POST /messages/repeat?count=N`
  - Load test endpoint: create `N` copies.
- `GET /messages/success?limit=100`
  - Return last 100 successful attempts.
- `GET /messages/failed?limit=100`
  - Return last 100 failed attempts.
- `GET /healthz`
  - Health endpoints.

Recent outcomes performance requirement:
- Avoid listing large S3 prefixes for recent outcomes.
- Serve recent outcomes from a bounded cache (e.g., maxlen=100 deque or Redis list semantics).

## 6) Mock SMS provider contract (required)

The mock SMS provider is a separate single container with:

- Endpoint: `POST /send`
- Request JSON:
  - `to`: string
  - `body`: string
  - `shouldFail`: optional boolean

Failure behavior:
- If `shouldFail=true`, always fail.
- Otherwise, fail a fixed fraction of requests using a configurable failure rate to ensure some messages fail during tests/load.

Failure signal:
- Worker observes failures via HTTP **non-2xx** responses.

Optional:
- The provider may simulate configurable latency to emulate slow/unreliable delivery.

## 7) Local development mapping (required)

- **Mock S3 provider**: in-process file reader/writer that implements the same persistence interface as the dedicated S3 persistence service.
- **Mock SMS provider**: runs as a separate container (single container) calling `POST /send`.
- **State ownership**: worker pods still use `HOSTNAME` and shard-range ownership semantics so the same code paths apply in local and cluster environments.

## 8) Testing plan (requirements-first)

Before meaningful implementation:

- Unit tests should cover:
  - deterministic shard assignment and shard-range ownership mapping
  - wakeup due-selection behavior: only process messages with `nextDueAt <= now`
  - retry timeline mapping from `attemptCount` to `nextDueAt`
  - terminal transition correctness: `pending -> success` and `pending -> failed`
  - recent outcomes bounded-cache behavior (no S3 listing dependency)
- Integration tests should cover:
  - S3 persistence via local mock S3 and/or an AWS simulator
  - end-to-end: API creates pending -> worker activation triggers attempt #1 -> due retries proceed -> terminal success/failed keys are written

