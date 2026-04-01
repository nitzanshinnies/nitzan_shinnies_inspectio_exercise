# P12.9 WS3 Iteration 3 Results

## Change under test

- Branch: `feat/v3-p12-9-tuning-iter-3`
- Candidate image: `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter3-20260401084203`
- Iteration-3 tuning scope:
  - bounded SQS delete concurrency in persistence transport consumer
  - writer flush occupancy floor for interval-triggered flushes
  - additive ack/flush-path diagnostics retained from WS2 snapshots

## Test protocol

- Full workload recycle before each profile run.
- Persist-off run:
  - `python scripts/v3_sustained_admit.py --api-base http://inspectio-l1:8080 --duration-sec 240 --concurrency 120 --batch 200 --body-prefix p12-9-iter3-off`
- Persist-on run:
  - `python scripts/v3_sustained_admit.py --api-base http://inspectio-l1:8080 --duration-sec 240 --concurrency 120 --batch 200 --body-prefix p12-9-iter3-on`
- Completion metric:
  - CloudWatch `AWS/SQS NumberOfMessagesDeleted` summed across `inspectio-v3-send-0..7`
  - 60s period

## Admission summary (driver)

- Persist off offered admit RPS: `13816.67` (`admitted_total=3316000`)
- Persist on offered admit RPS: `6969.17` (`admitted_total=1672600`)
- Admission ratio on/off: `50.44%`

## Completion summary (CloudWatch)

- Persist off combined avg completion RPS: `11488.31`
- Persist on combined avg completion RPS: `6024.82`
- Completion ratio on/off: `52.44%`
- Persist off peak completion RPS: `14113.10`
- Persist on peak completion RPS: `7103.88`

## Decision gate evaluation

Gate requirements from `ITER3_SE_HANDOFF_BRIEF.md`:

1. Completion ratio `>= 52.66%`
2. Improvement vs Iteration 2 `>= +5.00pp`
3. No correctness regression
4. No stability regression

Evaluation:

- (1) **FAIL**: `52.44% < 52.66%` (miss by `0.22pp`)
- (2) **PASS**: Iteration 2 ratio was `45.34%`; improvement is `+7.10pp`
- (3) **PASS**: WS3 regression suite passed (`38 passed`)
- (4) **PASS with caveat**: both jobs completed, but off job recorded transient failed pod attempts (`failed=2`, `succeeded=1`) before completion.

## Outcome

Iteration 3 is **NO-GO** for promotion because the completion-ratio threshold was not met.

Rollback executed to previous known-good image:

- rollback image:
  `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter2-20260331224309`
- all non-redis deployments reset and rolled out successfully.

## Artifacts

- `off-allpods.log`
- `on-allpods.log`
- `off_start.txt`
- `off_end.txt`
- `on_start.txt`
- `on_end.txt`
- `sustain_summaries.json`
- `cw_metrics.json`
