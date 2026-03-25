# Queue Optimization Session Findings

Date: 2026-03-23
Branch: `feature-worker-queue-optimization`

## Objective

Improve end-to-end drain performance for `POST /messages/repeat` by:
- reducing `list-prefix` pressure
- moving to queue-first worker flow
- making worker-side downstream publishing non-blocking

## Implemented Changes

1. Queue-first drain detection and counter
- Added Redis-backed pending counter (`common/pending_counter.py`).
- API increments counter on enqueue (`/messages`, `/messages/repeat`).
- Worker decrements counter when pending is removed/terminalized.
- Added internal endpoint: `GET /internal/v1/pending-count`.
- Load script uses API pending counter for drain (falls back to persistence list-prefix).

2. Worker queue optimization
- Changed worker tick from full discovery-every-tick to periodic discovery.
- Added discovery interval config in worker settings.
- Activation queue is now primary hot path; discovery is reconciliation cadence.

3. Removed duplicate terminal scans
- Kept pre-dispatch terminal scan path.
- Removed extra scans inside lifecycle transition functions.

4. Non-blocking notifier from worker
- Worker outcome publish now uses async bounded queue + background sender task.
- `publish()` enqueues and returns immediately.
- Retry/backoff happens in background task.
- Added clean shutdown drain (`runtime.aclose()` and app lifespan integration).

## Validation Performed

### Unit/Integration
- Worker runtime/config tests pass after each change-set.
- Notification integration tests pass after non-blocking notifier change.

### Local (in-memory/mock S3)
- 100-message run completed in ~5-7s range in latest iterations.
- Integrity checks pass locally when baseline is clean.

### EKS (S3-backed)
- Cleaned stack repeatedly before runs (workers down, lifecycle prefixes deleted, Redis flush, service restarts, workers up).
- 100-message run characteristics after latest deploy:
  - submit ~0.48-0.51s
  - drain reaches pending=0
  - total wall-clock before integrity call ~15s (`real ~15.2s`)
  - resulting lifecycle counts: success=100, failed=0, pending=0, notifications=100

Note: repeated `kubectl port-forward` disconnects caused script integrity step failures (`RemoteProtocolError`). Data-plane counts confirm completion despite these connectivity interruptions.

## Key Finding

The dominant bottleneck on EKS remains S3-backed persistence operation volume/latency in the worker lifecycle path.

Even after:
- queue-first activation
- reduced prefix scanning
- non-blocking notification publish

the EKS drain time improvement is limited because per-message lifecycle persistence work still requires multiple S3-backed operations.

## What Did NOT Materially Help on EKS

- `awswrangler` was investigated conceptually and is not a fit for this transactional key-level workload.
- Notification decoupling improved architecture and worker isolation, but did not materially reduce EKS end-to-end time on its own.

## Recommended Next Steps (High Impact)

1. Batch lifecycle persistence operations inside worker tick
- Group terminal writes and pending deletes, minimize one-by-one I/O.

2. Reduce object churn per message
- Minimize number of S3 keys touched in hot path.

3. Keep S3 as durability sink, move hot state elsewhere
- Use Redis/Dynamo-style hot state for queue/lifecycle transitions, flush/compact asynchronously to S3.

4. Improve test harness stability for EKS validation
- Replace fragile local port-forward dependency for integrity calls (or add resilient retries around integrity request in script).

## Useful Commands Used

Deploy latest image:
- `docker buildx build --platform linux/amd64 -t 194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-exercise:latest --push .`
- `kubectl -n inspectio rollout restart deployment/api deployment/persistence statefulset/worker deployment/health-monitor deployment/mock-sms`

Run EKS test (100):
- `python3 scripts/full_flow_load_test.py --kubernetes --api-base http://127.0.0.1:18000 --health-monitor-base http://127.0.0.1:18003 --persistence-base http://127.0.0.1:18001 --sizes 100 --http-timeout-sec 300 --integrity-timeout-sec 900 --drain-timeout-sec 1800`

