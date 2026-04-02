# P12.8 Sharded Persistence Rollout Report

## Scope

Remaining P12.8 execution work after code integration:

- run canary shard routing in EKS,
- roll out full shard-aligned persistence routing/writers,
- rerun persistence off/on benchmark profiles,
- refresh throughput gate report and store evidence artifacts.

## Environment

- cluster: `nitzan-inspectio` (`inspectio` namespace, us-east-1)
- image: `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-8-rollout-20260331223254`
- send shards: `K=8` (`inspectio-v3-send-0..7`)
- persistence queues: `inspectio-v3-persist-transport-0..7`
- persistence S3 prefix: `state/p12_8`

## Rollout execution

### 1) Preconditions and fixes

- Created persistence transport queues `inspectio-v3-persist-transport-0..7`.
- Added inline IAM policy `InspectioP12_8S3Access` on role `eksctl-inspectio-v3-app` for:
  - `s3:ListBucket` on the persistence bucket.
  - `s3:GetObject|PutObject|DeleteObject` on bucket objects.
- Built and pushed P12.8 image tag above.

### 2) Canary

- Applied shard writer deployments.
- Canary queue map:
  - shard 0 -> `persist-transport-0`
  - shards 1..7 -> legacy single queue `persist-transport`
- Scaled:
  - `inspectio-persistence-writer-shard-0=1`
  - `inspectio-persistence-writer-shard-1..7=0`
  - singleton `inspectio-persistence-writer=1`
- Recycled full stack and ran canary benchmark job.
- Observed healthy startup for both active writers and successful benchmark completion.

### 3) Full shard routing

- Updated queue map to full shard alignment:
  - shard s -> `persist-transport-s` for `s=0..7`.
- Scaled:
  - `inspectio-persistence-writer-shard-0..7=1`
  - singleton `inspectio-persistence-writer=0` (disabled, rollback-ready)
- Recycled full stack before each benchmark profile run (`off` then `on`).

## Benchmark and gate outcome

- Updated `plans/v3_phases/P12_7_THROUGHPUT_REPORT.md` from fresh in-cluster runs.
- Classification remains `hard_fail_completion` (merge blocked by completion gate).
- Relative to prior single-writer evidence, the sharded run improved:
  - completion ratio from `44.11%` to about `50.07%`,
  - persistence lag cap signal from prior breach to `0 ms` max observed queue oldest age in sampled windows.

## Evidence

Artifacts: `plans/v3_phases/artifacts/p12_8/`

- `persist-off.raw.log`, `persist-on.raw.log`
- `persist-off.json`, `persist-on.json`
- `off_window_utc.txt`, `on_window_utc.txt`
- `benchmark_metrics.json`
- `configmap_live.json`, `deployments_live.json`, `profile_equivalence.json`

