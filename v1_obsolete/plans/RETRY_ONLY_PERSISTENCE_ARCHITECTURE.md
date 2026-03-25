# Retry-Only Persistence Architecture

Date: 2026-03-23
Status: Implemented behind feature flag

## Goal

Support very high message throughput by removing S3 from the first-attempt hot path, while still satisfying restart durability for retries.

Directive interpretation:
- Persist retry state to S3 so the system survives restarts.
- Only retries (`attemptCount >= 1`) must be durable.

## Behavior Contract

- First-attempt pending (`attemptCount == 0`)
  - Stored in Redis staging.
  - Not persisted to S3 in retry-only mode.
  - If the system fully loses Redis before first dispatch, these messages may be lost.
- Retry pending (`attemptCount >= 1`)
  - Persisted to S3 (same pending key).
  - Recovered on worker restart via normal discovery.

## Runtime Flags

- `INSPECTIO_RETRY_ONLY_PERSISTENCE=true`
  - Enables retry-only durability behavior.
  - API stages initial pending records in Redis without enqueueing stream flush writes.
  - Worker enables Redis read-through staging even when stream flush mode is off.
- `INSPECTIO_PENDING_STREAM_REDIS_URL` (or `REDIS_URL`)
  - Required in retry-only mode for staging reads/writes.

## Data Flow

1. API accepts message and builds pending record (`attemptCount=0`).
2. API writes pending record to Redis staging key only.
3. API triggers worker activation (best-effort), and worker can discover staged keys during periodic discovery.
4. Worker first attempt:
   - Success: publish outcome, remove pending, no terminal S3 write in retry-only mode.
   - Failure: increment `attemptCount`, compute `nextDueAt`, persist updated pending to S3.
5. Subsequent retries operate from S3-backed pending state.

## Design Notes

- `StagingPersistence.list_prefix()` merges Redis-staged keys with S3 keys.
  - This preserves periodic discovery fallback if activation HTTP fails.
- `StagingPersistence.put_object(s)` deletes same-key Redis staging entries before S3 writes.
  - Prevents stale attempt `0` reads after first retry is persisted.

## Test Plan

- Unit: staging-only API writes do not enqueue stream flush entries.
- Unit: staging persistence list discovery includes staged keys.
- Unit: staging entries are cleared when same key is persisted.
- Unit: retry-only mode skips first-attempt terminal S3 writes.
- Integration: retry state survives worker restart and resumes.

## Rollout

1. Enable `INSPECTIO_RETRY_ONLY_PERSISTENCE=true` in non-prod.
2. Verify throughput gain and retry recovery behavior.
3. Monitor retry backlog and notification consistency.
4. Promote gradually to production.
