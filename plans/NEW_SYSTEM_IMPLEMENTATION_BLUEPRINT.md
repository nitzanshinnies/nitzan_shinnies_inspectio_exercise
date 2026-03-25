# NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md

## 1) Goal

Implement a throughput-oriented SMS retry system that preserves the assignment contract while removing known bottlenecks from synchronous request orchestration and per-message S3 hot-path writes.

Primary outcomes:

- sustain high ingest throughput (`POST /messages/repeat`) without 60s timeout failures;
- preserve retry correctness and crash resilience with S3-backed recovery;
- keep exact retry schedule semantics and 500ms scheduler cadence.

## 2) Constraints from assignment

The implementation must preserve:

- `newMessage(Message m)` immediate first attempt semantics (attempt #1 at 0s);
- `wakeup()` every 500ms exact scheduler heartbeat;
- retry deadlines: `0.5s, 2s, 4s, 8s, 16s` and fail after attempt #6;
- durability across restart using S3 as source of truth for recovery;
- API/UI:
  - `POST /messages`
  - `POST /messages/repeat?count=N`
  - `GET /messages/success?limit=100`
  - `GET /messages/failed?limit=100`

## 3) Architecture (target)

### 3.1 Planes

1. **Ingress plane** (API):
   - accepts request, validates payload, assigns `messageId`, emits ingest event;
   - returns quickly after durable ingest append (not after worker activation/send).

2. **Scheduler/execution plane** (workers):
   - partition ownership by shard;
   - immediate dispatch trigger for attempt #1;
   - 500ms tick drives due retries from in-memory timing wheel/min-heap.

3. **Durability plane** (S3 journal + snapshot):
   - append-only retry state journal in micro-batches;
   - periodic shard snapshots for bounded restart replay.

4. **Read plane** (outcomes service + Redis):
   - terminal outcomes indexed in Redis bounded lists;
   - optional hydration from S3 terminal/outcome logs on cold start.

### 3.2 Why this fixes observed failures

- removes blocking API->worker synchronous orchestration from submit critical path;
- replaces per-transition S3 object chatter with batch append semantics;
- isolates scheduler timing correctness from persistence/list-prefix polling delays;
- decouples "ingest SLO" from "drain completion + integrity scanning."

## 4) Component contracts

### 4.1 Ingest event contract

Event type: `MessageIngestedV1`

Required fields:

- `messageId: string`
- `payload: { body: string, ... }`
- `receivedAtMs: int`
- `shardId: int`
- `idempotencyKey: string` (or equal to `messageId`)

Rules:

- event append must be durable before API returns success;
- duplicate `idempotencyKey` must not create duplicate active state.

### 4.2 Retry state contract

Record type: `RetryStateV1`

Fields:

- `messageId: string`
- `attemptCount: int` (0..6)
- `nextDueAtMs: int`
- `status: pending|success|failed`
- `lastError: string|null`
- `payload: object` (data required to call `send`)
- `updatedAtMs: int`

Invariant:

- for `status=pending`, `nextDueAtMs` must be monotonic increasing per attempt;
- terminal states (`success|failed`) are immutable except metadata enrichment.

### 4.3 Outcome contract

Event type: `MessageTerminalV1`

Fields:

- `messageId`
- `terminalStatus: success|failed`
- `attemptCount`
- `finalTimestampMs`
- `reason` (required for failed)

Read API derives `last 100` from this stream/index, not from full S3 scans.

## 5) Data layout

### 5.1 S3 keys

Bucket: `<configured-bucket>`

- Journal segments:
  - `state/journal/<shardId>/<yyyy>/<MM>/<dd>/<hh>/<segmentStartMs>-<seq>.ndjson.gz`
- Snapshots:
  - `state/snapshot/<shardId>/latest.json`
  - `state/snapshot/<shardId>/<epochMs>.json`
- Optional terminals (audit):
  - `state/terminal/<yyyy>/<MM>/<dd>/<hh>/<messageId>.json`

### 5.2 Redis keys (read plane + transient indexes)

- `inspectio:outcomes:success` (bounded list)
- `inspectio:outcomes:failed` (bounded list)
- `inspectio:idempotency:<idempotencyKey>` (TTL map to `messageId`)

## 6) Scheduling model

### 6.1 Immediate attempt

- on ingest append success, enqueue item to shard-local immediate queue;
- worker processes immediate queue without waiting for next tick;
- if queue handoff fails, tick-based due scan picks it up within 500ms.

### 6.2 Retry cadence

Backoff table (fixed per assignment):

- attempt 2: +0.5s
- attempt 3: +2s
- attempt 4: +4s
- attempt 5: +8s
- attempt 6: +16s

Rule:

- never execute retry before `nextDueAtMs`;
- track and export scheduler lag (`nowMs - nextDueAtMs` when processed).

## 7) AWS runtime blueprint

### 7.1 Recommended stack

- **EKS**: API, worker, notification, health-monitor;
- **S3**: durability (journal + snapshot + optional terminal logs);
- **ElastiCache Redis**: outcomes hot index and idempotency cache;
- **Kinesis or MSK**: durable high-throughput ingest stream (preferred over in-process queue);
- **ALB/Ingress**: API/UI endpoints.

### 7.2 IAM

- IRSA role for writer components with scoped S3 prefix access;
- separate read-only role for health/analysis if needed;
- no static AWS secrets in ConfigMaps.

## 8) Observability blueprint

### 8.1 Required metrics

- ingest:
  - `api_submit_latency_ms` (p50/p95/p99)
  - `ingest_events_appended_total`
  - `ingest_rejected_total`
- scheduler:
  - `scheduler_tick_duration_ms`
  - `scheduler_lag_ms`
  - `attempts_total{attempt,status}`
- persistence:
  - `journal_flush_batch_size`
  - `journal_flush_latency_ms`
  - `snapshot_latency_ms`
  - `s3_errors_total`
- outcomes:
  - `outcome_publish_latency_ms`
  - `outcome_index_write_errors_total`

### 8.2 Required logs

Structured logs with `messageId`, `shardId`, `attemptCount`, `phase`, `traceId`.

## 9) Rollout plan (phased)

## Phase 1 - API critical path decoupling

Deliverables:

- submit returns after durable ingest append only;
- worker activation/send fully backgrounded;
- add ingest/activation metrics.

Acceptance:

- no 60s submit timeout at 10k batch profile;
- p95 submit latency materially reduced vs baseline.

## Phase 2 - Scheduler hardening

Deliverables:

- shard-local immediate queue + 500ms tick coexistence;
- deterministic retry timing checks;
- idempotency handling at ingest.

Acceptance:

- deadline compliance under stress (no early retries, bounded lag);
- duplicate ingest calls do not duplicate active work.

## Phase 3 - S3 journal + snapshot durability

Deliverables:

- micro-batched journal writer;
- periodic snapshots;
- restart replay logic (snapshot + journal tail).

Acceptance:

- crash/restart recovers pending retry workload correctly;
- S3 operation rate per message significantly reduced.

## Phase 4 - Read plane stabilization

Deliverables:

- Redis outcomes as source for `last 100` APIs;
- bounded hydration strategy with leader lock;
- optional terminal audit sink to S3.

Acceptance:

- `GET /messages/success|failed?limit=100` stays low-latency at load;
- no destructive hydration races in multi-replica notification service.

## 10) Test blueprint

### 10.1 Functional

- first attempt runs immediately after ingest;
- retry deadlines exactly follow assignment schedule;
- fail after 6th failed attempt;
- success/failed APIs return recent terminal records.

### 10.2 Reliability

- kill worker mid-flight -> restart -> recover from S3 journal/snapshot;
- Redis unavailable transiently -> outcomes eventual catch-up path;
- ingest stream backpressure -> explicit rejection policy and no silent drop.

### 10.3 Performance

- in-cluster AWS load jobs only;
- measure separately:
  - submit throughput,
  - scheduler throughput,
  - terminalization throughput,
  - durability write throughput.

## 11) Risks and mitigations

- **Risk:** eventual consistency between terminal event and read API.
  - **Mitigation:** durable terminal event log + retryable index update.
- **Risk:** shard imbalance.
  - **Mitigation:** shard cardinality > worker count and rebalance tooling.
- **Risk:** replay lag after large outage.
  - **Mitigation:** frequent snapshots + bounded journal segment size.

## 12) Definition of done

- submit path reliably handles large repeat batches without request-time disconnect pattern;
- retry timing and max-attempt semantics pass deterministic tests;
- restart recovery validated from S3 durability artifacts;
- last-100 APIs remain stable and fast under load;
- documented runbook for AWS deployment, scaling, and recovery.

