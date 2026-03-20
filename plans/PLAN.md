# nitzan_shinnies_inspectio_exercise - General Plan

This document mirrors the architect’s “High-Throughput SMS Retry Scheduler” specification and defines the required system behaviors for the interview exercise.

## 1) System overview

- Build a distributed system that can handle tens-of-thousands of SMS messages per second.
- Use AWS S3 as the primary source of truth for persistence and crash resilience.
- Expose a REST API (Python/FastAPI) for message submission and for querying recent outcomes.
- Run the scheduler/worker logic inside a Kubernetes StatefulSet so each pod has stable identity for deterministic sharding.

## 2) Stack & runtime requirements

- Python 3.11+
- FastAPI
- `aioboto3` (async AWS operations)
- `uvicorn` to run the FastAPI service(s)

## 3) S3 data model & bucket layout

All message state is persisted in S3 under the following key prefixes:

- Pending:
  - `state/pending/<shard>/<messageId>.json`
- Success:
  - `state/success/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`
- Failed (terminal):
  - `state/failed/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`

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
- `nextDueAt`: epoch milliseconds
- `status`: one of `pending`, `success`, `failed`
- `payload`: SMS input (`to`, `body`)
- `history`: optional timestamps/outcomes

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

- Exactly one worker pod is responsible for the `state/pending/<shard>/` prefix for any given `shard_id` (so only that pod reads/writes that prefix).

## 5) Core message lifecycle & retry timeline

### newMessage hook (requirements)

Upon activation for a given message:

1. **Idempotency check**
   - Verify whether `messageId` already exists in the local cache or in S3.
2. **Initial persistence**
   - Persist the message under `state/pending/<shard>/<messageId>.json`.
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
   - Load test endpoint: create `N` copies.
3. `GET /messages/success?limit=100`
   - Return the last 100 successful attempts.
4. `GET /messages/failed?limit=100`
   - Return the last 100 failed attempts.
5. `GET /healthz`
   - Basic health endpoint(s).

Recent outcomes performance requirement:

- Do not list large S3 prefixes to serve “recent outcomes”.
- Maintain a bounded recent cache for the last 100 outcomes (e.g., `collections.deque(maxlen=100)` or a Redis list).

## 8) Mock SMS provider container (requirements)

**Detailed plan:** [`plans/MOCK_SMS.md`](MOCK_SMS.md) (intermittent/probabilistic failures, **module-level behavior constants**, and validation checklist).

The mock SMS provider must be a separate container (single service) with the sole purpose of simulating SMS sends for the worker. **No web UI** for tuning behavior; all tunable **behavior** parameters are **named constants in the mock’s Python module** (change by editing code / redeploy).

- Endpoint:
  - `POST /send`
- Request JSON:
  - `to`: string
  - `body`: string
  - `shouldFail`: optional boolean
  - `messageId`: optional string (logging/tracing; worker may include it)
- Failure behavior:
  - If `shouldFail=true`, the provider must always fail the request.
  - Otherwise, the provider must fail a fixed fraction of requests per the module’s **`FAILURE_RATE`** constant (so that some messages fail during load).
  - Simulated failures should reflect realistic categories: **failed to send** (e.g. invalid recipient, line error) vs **service unavailable** (transient outage); both are returned as **`5xx`** (see `MOCK_SMS.md`).
- Success/failure signal (send outcome):
  - Success → HTTP **`2xx`**.
  - Simulated send failure → HTTP **`5xx`** (not **`4xx`** on the normal send path; **`4xx`** reserved for bad requests to the mock).
- Optional simulated latency:
  - Governed by module constants (e.g. **`LATENCY_MS`**) per `MOCK_SMS.md`—not a separate admin UI.

## 9) Testing plan (requirements-first)

Before meaningful implementation:

- Unit test requirements:
  - Shard assignment and worker shard range ownership mapping
  - `nextDueAt` computation for the architect’s retry timeline
  - Correct S3 state transitions: `pending -> success` and `pending -> failed`
  - “Recent outcomes” cache behavior (bounded to 100)
- Integration test requirements:
  - Simulate S3 using LocalStack or moto
  - End-to-end flow: API creates pending state -> worker processes retries -> terminal success/failed state written to the correct S3 keys

