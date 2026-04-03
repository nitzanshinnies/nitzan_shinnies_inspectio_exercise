# P12.7 Throughput Comparison Report

## Benchmark identity
- image tag: `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-8-rollout-20260331223254`
- configmap sha256: `34fa799faa38c97413f1f9bcc9ea33a5d22d4b83ed39fdef29dd802e317592c5`
- profile equivalence: `same image/replicas/shards/job shape/region; only persistence emit + writer activation differed`

## Inputs and artifacts
- persist-off JSON: `plans/v3_phases/artifacts/p12_8/persist-off.json`
- persist-on JSON: `plans/v3_phases/artifacts/p12_8/persist-on.json`
- phase index: `-1`
- persist-off CloudWatch window: `2026-03-31T19:41:16Z..2026-03-31T19:52:27Z`
- persist-on CloudWatch window: `2026-03-31T19:43:34Z..2026-03-31T19:54:44Z`
- CloudWatch evidence command/reference: `AWS/SQS NumberOfMessagesDeleted (send shards 0..7, period=60, Sum) + ApproximateAgeOfOldestMessage (persist shards 0..7, period=60, Maximum)`

## Gate result
- admission throughput ratio (on/off): `108.73%`
- hard gate (>= 70.0%): `PASS`
- target gate (>= 85.0%): `PASS`
- completion hard gate (>= 70.0%): `FAIL`
- completion target gate (>= 85.0%): `MISS`
- classification: `hard_fail_completion`
- merge policy outcome: `block`
- waiver note: `none`

## Required outputs
- admit throughput off/on: `47065.49` / `51173.39` recipients/sec
- combined send-queue delete throughput off/on: `29.806259314456035` / `14.925373134328359` msgs/sec
- send delete throughput ratio (on/off): `50.07%`
- writer lag ms off/on: `0.0` / `0.0`
- writer flush latency ms off/on: `0.0` / `0.0`
- writer lag cap ms: `30000.0`
- flush latency cap ms: `5000.0`
- error rate off/on: `0.0` / `0.0`
- error rate delta (on-off): `0.0`

## Per-dimension gate table
| Dimension | Hard Pass | Target Pass |
|---|---|---|
| Admission ratio | `True` | `True` |
| Completion ratio | `False` | `False` |

## Stability
- off run stability: `stable: no crash loops observed; queue drain completed`
- on run stability: `stable: no crash loops observed; per-shard persistence queue oldest-age remained zero`
- crash-loop check off/on (must be false): `False` / `False`
- crash-loop pass: `True`
- writer lag cap pass: `True`
- flush latency cap pass: `True`

## Phase snapshots
```json
{
  "persist_off_phase": {
    "recipients_admitted": 10000,
    "max_total_sec_cap": null,
    "parallel_admission": 1,
    "persistence_mode": "off",
    "admission_sec": 0.212,
    "admission_rps": 47065.49,
    "chunks": 1,
    "completion_detection": "outcomes_get_success_capped",
    "chunk_latency_ms_p50": 212.43,
    "chunk_latency_ms_p95": 212.43,
    "chunk_latency_ms_p99": 212.43
  },
  "persist_on_phase": {
    "recipients_admitted": 10000,
    "max_total_sec_cap": null,
    "parallel_admission": 1,
    "persistence_mode": "on",
    "admission_sec": 0.195,
    "admission_rps": 51173.39,
    "chunks": 1,
    "completion_detection": "outcomes_get_success_capped",
    "chunk_latency_ms_p50": 195.38,
    "chunk_latency_ms_p95": 195.38,
    "chunk_latency_ms_p99": 195.38
  }
}
```

## Composite rationale (machine-readable)
```json
{
  "classification": "hard_fail_completion",
  "admission_hard_pass": true,
  "admission_target_pass": true,
  "completion_hard_pass": false,
  "completion_target_pass": false,
  "writer_lag_cap_pass": true,
  "flush_latency_cap_pass": true,
  "crash_loop_pass": true
}
```
