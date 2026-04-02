# P12.9 WS3 Iteration 4 Results

## Change under test

- Branch: `feat/v3-p12-9-tuning-iter-4-checkpoint-cadence`
- Candidate image: `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter4-20260401123015`
- Scope lock: checkpoint cadence + additive checkpoint-cost metrics only.
- Config knob under test: `INSPECTIO_V3_PERSISTENCE_CHECKPOINT_EVERY_N_FLUSHES` (`1..20`, default `1`).

## Test gate before deploy

- Unit/integration correctness suites passed before benchmark (`44 passed`), including:
  - cadence logic (`N=1`, `N>1`, bounds)
  - segment-before-checkpoint contract
  - sparse-checkpoint replay correctness
  - P12.4-P12.6 critical suites

## Benchmark protocol (hygiene-locked)

- Full stack recycle before each profile.
- Shape (off/on identical): `--duration-sec 240 --concurrency 120 --batch 200`
- Kubernetes Job semantics: `backoffLimit: 0`, `restartPolicy: Never`.
- Completion metric: CloudWatch `AWS/SQS NumberOfMessagesDeleted` summed across `inspectio-v3-send-0..7` (period `60s`, stat `Sum`).

## Admission summary (driver)

- Persist off offered admit RPS: `14093.33` (`admitted_total=3382400`)
- Persist on offered admit RPS: `6842.5` (`admitted_total=1642200`)
- Admission ratio on/off: `48.55%`

## Completion summary (CloudWatch)

- Persist off combined avg completion RPS: `8053.34`
- Persist on combined avg completion RPS: `3585.41`
- Completion ratio on/off: `44.52%`
- Gain vs WS3.1 baseline (`44.84%`): `-0.32pp`

## Decision gate evaluation

Gate requirements from `ITER4_SE_HANDOFF_BRIEF.md`:

1. completion ratio `>= 52.66%`
2. gain vs WS3.1 (`44.84%`) `>= +5.00pp`
3. no correctness regressions
4. no stability regressions

Evaluation:

- (1) **FAIL**: `44.52% < 52.66%`
- (2) **FAIL**: `-0.32pp < +5.00pp`
- (3) **PASS**: predeploy correctness gate passed (`44 passed`)
- (4) **PASS**: final persisted off/on artifacts each show `succeeded=1`, `failed=0`

## Outcome

Iteration 4 is **NO-GO**.

Rollback executed to previous known-good image/config:

- rollback image: `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter2-20260331224309`
- `INSPECTIO_V3_PERSIST_EMIT_ENABLED=true`
- all non-redis deployments rolled out successfully after rollback
- EKS nodegroup scaled back to `desiredSize=0`

## Artifacts

Required bundle:

- `off_start.txt`, `off_end.txt`
- `on_start.txt`, `on_end.txt`
- `off-allpods.log`, `on-allpods.log`
- `off_job_status.json`, `on_job_status.json`
- `sustain_summaries.json`
- `cw_metrics.json`
- `measurement_manifest.json`

Additional retry/debug evidence retained:

- `off-allpods-attempt1.log`, `off_job_status_attempt1.json`
- `off-allpods-attempt3.log`, `off_job_status_attempt3.json`
- `on-allpods-attempt1.log`, `on_job_status_attempt1.json`
- `on-allpods-attempt2.log`, `on_job_status_attempt2.json`
- `on-allpods-attempt3.log`, `on_job_status_attempt3.json`
