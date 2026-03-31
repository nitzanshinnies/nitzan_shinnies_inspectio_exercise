# P12.7 Throughput Comparison Report

## Benchmark identity
- image tag: `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-7-fix-20260331163605`
- configmap sha256: `b44f7af029479eeafb581857c70277eae1341b5e1f1e70f8a11a53cdf821de15`
- profile equivalence: `same image/replicas/shards/job shape/region; only persistence emit + writer activation differed`

## Inputs and artifacts
- persist-off JSON: `plans/v3_phases/artifacts/p12_7/persist-off.json`
- persist-on JSON: `plans/v3_phases/artifacts/p12_7/persist-on.json`
- phase index: `-1`
- persist-off CloudWatch window: `2026-03-31T13:37:55Z..2026-03-31T13:42:55Z`
- persist-on CloudWatch window: `2026-03-31T13:39:20Z..2026-03-31T13:44:20Z`
- CloudWatch evidence command/reference: `AWS/SQS NumberOfMessagesDeleted (send shards 0..7, period=60, Sum), ApproximateAgeOfOldestMessage (inspectio-v3-persist-transport, period=60, Maximum)`

## Gate result
- admission throughput ratio (on/off): `115.23%`
- hard gate (>= 70.0%): `PASS`
- target gate (>= 85.0%): `PASS`
- classification: `target_pass`
- merge policy outcome: `target-pass`
- waiver note: `none`

## Required outputs
- admit throughput off/on: `39744.7` / `45796.03` recipients/sec
- combined send-queue delete throughput off/on: `58.53` / `25.82` msgs/sec
- send delete throughput ratio (on/off): `44.11%`
- writer lag ms off/on: `0.0` / `52000.0`
- error rate off/on: `0.0` / `0.0`
- error rate delta (on-off): `0.0`

## Stability
- off run stability: `stable: no crash loops observed; queue drain completed`
- on run stability: `stable: no crash loops observed; writer lag bounded`

## Phase snapshots
```json
{
  "persist_off_phase": {
    "recipients_admitted": 10000,
    "max_total_sec_cap": null,
    "parallel_admission": 1,
    "persistence_mode": "off",
    "admission_sec": 0.252,
    "admission_rps": 39744.7,
    "chunks": 1,
    "completion_detection": "outcomes_get_success_capped",
    "chunk_latency_ms_p50": 251.57,
    "chunk_latency_ms_p95": 251.57,
    "chunk_latency_ms_p99": 251.57
  },
  "persist_on_phase": {
    "recipients_admitted": 10000,
    "max_total_sec_cap": null,
    "parallel_admission": 1,
    "persistence_mode": "on",
    "admission_sec": 0.218,
    "admission_rps": 45796.03,
    "chunks": 1,
    "completion_detection": "outcomes_get_success_capped",
    "chunk_latency_ms_p50": 218.32,
    "chunk_latency_ms_p95": 218.32,
    "chunk_latency_ms_p99": 218.32
  }
}
```
