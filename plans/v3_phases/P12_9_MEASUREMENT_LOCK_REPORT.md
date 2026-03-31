# P12.9 WS1 Measurement Integrity Lock Report

## Scope

Workstream 1 from `P12_9_COMPLETION_THROUGHPUT_RESCUE_PLAN.md`:

- lock benchmark profile parity for completion measurement,
- capture machine-readable CloudWatch query definitions,
- run two consecutive off/on benchmark reruns,
- validate reproducibility threshold.

## Locked profile

- image tag: `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-8-rollout-20260331223254`
- send shard count: `8`
- persistence shard count: `8`
- load job shape:
  - `scripts/v3_sustained_admit.py`
  - `--duration-sec 240 --concurrency 120 --batch 200 --body-prefix p12-9-ws1`
- completion metric source: `AWS/SQS NumberOfMessagesDeleted`, stat `Sum`, period `60s`, dimensions `inspectio-v3-send-0..7`
- preprocessing:
  - preload: `60s`
  - tail: `120s`
  - gate metric: `combined_avg_rps`

## Reproducibility result

- reproducibility metric: `combined_avg_rps` (`delete_total / query_window_seconds`)
- threshold: `<= 10%` variance between consecutive reruns per profile
- overlap check: `PASS` (`overlap_detected=false`)
- observed:
  - off gate values: `[4849.0741, 4669.4253]`
  - on gate values: `[2948.2679, 2721.5596]`
  - off variance: `3.775%`
  - on variance: `7.997%`
  - secondary telemetry:
    - off peak rps runs: `[8939.9833, 8601.4833]`
    - on peak rps runs: `[4591.4500, 4502.7833]`
- status: `PASS`

## Run windows

- r1 off:
  - job window: `2026-03-31T20:29:10Z..2026-03-31T20:33:22Z`
  - query window: `2026-03-31T20:28:10Z..2026-03-31T20:35:22Z`
- r1 on:
  - job window: `2026-03-31T20:38:11Z..2026-03-31T20:42:24Z`
  - query window: `2026-03-31T20:37:11Z..2026-03-31T20:44:24Z`
- r2 off:
  - job window: `2026-03-31T20:50:16Z..2026-03-31T20:54:31Z`
  - query window: `2026-03-31T20:49:16Z..2026-03-31T20:56:31Z`
- r2 on:
  - job window: `2026-03-31T21:04:16Z..2026-03-31T21:08:32Z`
  - query window: `2026-03-31T21:03:16Z..2026-03-31T21:10:32Z`

Each run reported `active_period_count=5` (>= required `3`) in `benchmark_metrics_raw.json`.

## Exact commands used

### Workload recycle list (explicit)

- Deployments restarted and awaited before every run:
  - `inspectio-api`
  - `inspectio-l1`
  - `inspectio-expander`
  - `inspectio-worker-shard-0`
  - `inspectio-worker-shard-1`
  - `inspectio-worker-shard-2`
  - `inspectio-worker-shard-3`
  - `inspectio-worker-shard-4`
  - `inspectio-worker-shard-5`
  - `inspectio-worker-shard-6`
  - `inspectio-worker-shard-7`
  - `inspectio-persistence-writer-shard-0`
  - `inspectio-persistence-writer-shard-1`
  - `inspectio-persistence-writer-shard-2`
  - `inspectio-persistence-writer-shard-3`
  - `inspectio-persistence-writer-shard-4`
  - `inspectio-persistence-writer-shard-5`
  - `inspectio-persistence-writer-shard-6`
  - `inspectio-persistence-writer-shard-7`
  - `redis`

### Run-to-job mapping

| Run ID | Mode | Kubernetes Job |
|---|---|---|
| `r1_off` | persistence emit disabled | `inspectio-v3-p12-9-r1-off` |
| `r1_on` | persistence emit enabled | `inspectio-v3-p12-9-r1-on` |
| `r2_off` | persistence emit disabled | `inspectio-v3-p12-9-r2-off` |
| `r2_on` | persistence emit enabled | `inspectio-v3-p12-9-r2-on` |

### Concrete command sequence (copy/paste)

1. Set image variable:
   - `IMG=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-8-rollout-20260331223254`
2. Toggle mode for each run:
   - off mode: `kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"false"}}'`
   - on mode: `kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"true"}}'`
3. Recycle workloads for each run:
   - `for d in inspectio-api inspectio-l1 inspectio-expander inspectio-worker-shard-0 inspectio-worker-shard-1 inspectio-worker-shard-2 inspectio-worker-shard-3 inspectio-worker-shard-4 inspectio-worker-shard-5 inspectio-worker-shard-6 inspectio-worker-shard-7 inspectio-persistence-writer-shard-0 inspectio-persistence-writer-shard-1 inspectio-persistence-writer-shard-2 inspectio-persistence-writer-shard-3 inspectio-persistence-writer-shard-4 inspectio-persistence-writer-shard-5 inspectio-persistence-writer-shard-6 inspectio-persistence-writer-shard-7 redis; do kubectl -n inspectio rollout restart deployment/$d; done`
   - `for d in inspectio-api inspectio-l1 inspectio-expander inspectio-worker-shard-0 inspectio-worker-shard-1 inspectio-worker-shard-2 inspectio-worker-shard-3 inspectio-worker-shard-4 inspectio-worker-shard-5 inspectio-worker-shard-6 inspectio-worker-shard-7 inspectio-persistence-writer-shard-0 inspectio-persistence-writer-shard-1 inspectio-persistence-writer-shard-2 inspectio-persistence-writer-shard-3 inspectio-persistence-writer-shard-4 inspectio-persistence-writer-shard-5 inspectio-persistence-writer-shard-6 inspectio-persistence-writer-shard-7 redis; do kubectl -n inspectio rollout status deployment/$d --timeout=600s; done`
4. Create each run job:
   - `r1_off`:
     - `START=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$START" > plans/v3_phases/artifacts/p12_9/runs/r1_off_start.txt`
     - `kubectl -n inspectio delete job inspectio-v3-p12-9-r1-off --ignore-not-found`
     - `kubectl -n inspectio apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: inspectio-v3-p12-9-r1-off
  namespace: inspectio
spec:
  activeDeadlineSeconds: 900
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: inspectio-app
      restartPolicy: Never
      containers:
        - name: driver
          image: $IMG
          imagePullPolicy: Always
          env:
            - name: INSPECTIO_LOAD_TEST_API_BASE
              value: http://inspectio-l1:8080
          args:
            - python
            - scripts/v3_sustained_admit.py
            - --duration-sec
            - "240"
            - --concurrency
            - "120"
            - --batch
            - "200"
            - --body-prefix
            - "p12-9-ws1"
EOF`
     - `kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-r1-off --timeout=920s`
     - `kubectl -n inspectio logs job/inspectio-v3-p12-9-r1-off > plans/v3_phases/artifacts/p12_9/runs/r1_off.log`
     - `END=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$END" > plans/v3_phases/artifacts/p12_9/runs/r1_off_end.txt`
   - `r1_on`:
     - `START=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$START" > plans/v3_phases/artifacts/p12_9/runs/r1_on_start.txt`
     - `kubectl -n inspectio delete job inspectio-v3-p12-9-r1-on --ignore-not-found`
     - `kubectl -n inspectio apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: inspectio-v3-p12-9-r1-on
  namespace: inspectio
spec:
  activeDeadlineSeconds: 900
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: inspectio-app
      restartPolicy: Never
      containers:
        - name: driver
          image: $IMG
          imagePullPolicy: Always
          env:
            - name: INSPECTIO_LOAD_TEST_API_BASE
              value: http://inspectio-l1:8080
          args:
            - python
            - scripts/v3_sustained_admit.py
            - --duration-sec
            - "240"
            - --concurrency
            - "120"
            - --batch
            - "200"
            - --body-prefix
            - "p12-9-ws1"
EOF`
     - `kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-r1-on --timeout=920s`
     - `kubectl -n inspectio logs job/inspectio-v3-p12-9-r1-on > plans/v3_phases/artifacts/p12_9/runs/r1_on.log`
     - `END=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$END" > plans/v3_phases/artifacts/p12_9/runs/r1_on_end.txt`
   - `r2_off`:
     - `START=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$START" > plans/v3_phases/artifacts/p12_9/runs/r2_off_start.txt`
     - `kubectl -n inspectio delete job inspectio-v3-p12-9-r2-off --ignore-not-found`
     - `kubectl -n inspectio apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: inspectio-v3-p12-9-r2-off
  namespace: inspectio
spec:
  activeDeadlineSeconds: 900
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: inspectio-app
      restartPolicy: Never
      containers:
        - name: driver
          image: $IMG
          imagePullPolicy: Always
          env:
            - name: INSPECTIO_LOAD_TEST_API_BASE
              value: http://inspectio-l1:8080
          args:
            - python
            - scripts/v3_sustained_admit.py
            - --duration-sec
            - "240"
            - --concurrency
            - "120"
            - --batch
            - "200"
            - --body-prefix
            - "p12-9-ws1"
EOF`
     - `kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-r2-off --timeout=920s`
     - `kubectl -n inspectio logs job/inspectio-v3-p12-9-r2-off > plans/v3_phases/artifacts/p12_9/runs/r2_off.log`
     - `END=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$END" > plans/v3_phases/artifacts/p12_9/runs/r2_off_end.txt`
   - `r2_on`:
     - `START=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$START" > plans/v3_phases/artifacts/p12_9/runs/r2_on_start.txt`
     - `kubectl -n inspectio delete job inspectio-v3-p12-9-r2-on --ignore-not-found`
     - `kubectl -n inspectio apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: inspectio-v3-p12-9-r2-on
  namespace: inspectio
spec:
  activeDeadlineSeconds: 900
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: inspectio-app
      restartPolicy: Never
      containers:
        - name: driver
          image: $IMG
          imagePullPolicy: Always
          env:
            - name: INSPECTIO_LOAD_TEST_API_BASE
              value: http://inspectio-l1:8080
          args:
            - python
            - scripts/v3_sustained_admit.py
            - --duration-sec
            - "240"
            - --concurrency
            - "120"
            - --batch
            - "200"
            - --body-prefix
            - "p12-9-ws1"
EOF`
     - `kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-r2-on --timeout=920s`
     - `kubectl -n inspectio logs job/inspectio-v3-p12-9-r2-on > plans/v3_phases/artifacts/p12_9/runs/r2_on.log`
     - `END=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$END" > plans/v3_phases/artifacts/p12_9/runs/r2_on_end.txt`
5. Enforce spacing to keep query windows non-overlapping:
   - `sleep 120`
6. Generate WS1 artifacts:
   - `python scripts/v3_p12_9_measurement_lock.py --window-preload-seconds 60 --window-tail-seconds 120 --repro-metric combined_avg_rps --min-active-periods 3`

## Artifacts

- `plans/v3_phases/artifacts/p12_9/measurement_manifest.json`
- `plans/v3_phases/artifacts/p12_9/persist-off-window.txt`
- `plans/v3_phases/artifacts/p12_9/persist-on-window.txt`
- `plans/v3_phases/artifacts/p12_9/benchmark_metrics_raw.json`
- run logs/windows:
  - `plans/v3_phases/artifacts/p12_9/runs/r1_off.log`
  - `plans/v3_phases/artifacts/p12_9/runs/r1_on.log`
  - `plans/v3_phases/artifacts/p12_9/runs/r2_off.log`
  - `plans/v3_phases/artifacts/p12_9/runs/r2_on.log`
  
