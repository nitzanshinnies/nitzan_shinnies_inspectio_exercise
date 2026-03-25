# 20k AWS In-Cluster Load Test Findings

Date: 2026-03-25
Environment: EKS (`inspectio` namespace), in-cluster Job runner, real AWS S3 backend.

## Test Setup

- Harness: `scripts/full_flow_load_test.py`
- Job mode: `--kubernetes`
- Batch size: `--sizes 20000`
- Repeat chunking: `--repeat-chunk-max 10000` (two API submits)
- Scoped drain: `--scoped-drain-metrics --scoped-prefix-source notifications`
- Drain diagnostics: enabled
- Poll interval: `--drain-poll-sec 1.0`
- Timeouts: `--http-timeout-sec 600 --drain-timeout-sec 7200 --integrity-timeout-sec 7200`

Before running, the full stack was rollout-restarted (api, web, persistence, notification, mock-sms, health-monitor, redis, worker).

## Key Results

- API submit completed with `accepted=20000` in `1.84s`.
  - Approximate API-side accept burst rate: `~10,870 msg/s`.
- Drain completion:
  - `run_scoped_sec=560.37`
  - `global_pending_sec=560.39`
  - End-to-end drain throughput for this run: `20000 / 560.37 ~= 35.7 msg/s`.
- Drain loop profile:
  - `poll=159` at completion.
  - Late-poll `list_ms` reached multi-second values (example: `list_ms=5013.08` at poll 158 with `candidates=19960`).
  - Final poll: `matched=20000`, `pending_empty=true`.

## Interpretation

The system can accept a large burst quickly at the API boundary, but end-to-end completion (accepted -> processed -> persisted -> visible in scoped prefixes with pending empty) is much slower.

This run does **not** support a sustained claim of "tens of thousands of messages per second" for end-to-end processing. It supports:

- high short-lived API acceptance burst rate, and
- sustained end-to-end throughput on the order of tens of messages per second in this configuration.

## Why End-to-End Is Slow (Observed)

- Drain required many polls (`159`), and each poll incurs:
  - paged list-prefix scans over growing keysets,
  - pending probe,
  - plus fixed sleep interval (`1s`) between polls when not complete.
- As cardinality rose, per-poll list work increased significantly (`list_ms` growth), which lengthened wall-clock to completion.

## Notes / Caveats

- During observation, logs clearly showed drain completion metrics; post-drain integrity/lifecycle lines may appear later due to expensive integrity scan at this scale with long timeout settings.
- Findings are for this specific topology and settings (single workload profile, current replica counts, current AWS resources).
