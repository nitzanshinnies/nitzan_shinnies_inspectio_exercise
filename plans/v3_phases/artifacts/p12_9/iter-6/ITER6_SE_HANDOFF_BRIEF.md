# P12.9 WS3.4 Iteration-6 — SE Handoff Brief

Use this runbook for Iteration 6 only.

Detailed step-by-step execution playbook:

- `plans/v3_phases/artifacts/p12_9/iter-6/ITER6_SE_EXECUTION_PLAYBOOK.md`

Canonical execution spec (authoritative source for test run steps):

- `plans/v3_phases/P12_9_ITER6_TEST_EXECUTION_SPEC.md`

## 1) Scope lock

Allowed:

- decouple writer receive lane from flush/ack lane,
- bounded ack work queue,
- additive pipeline metrics,
- required tests + benchmark artifacts.

Not allowed:

- flush-tuning experiments unrelated to decoupling,
- ack strategy algorithm rewrites beyond queue-based decoupling,
- checkpoint cadence experiments,
- retry/backoff experiments,
- schema/replay/API changes.

## 2) Branch

```bash
git checkout -b feat/v3-p12-9-tuning-iter-6-writer-pipeline
```

## 3) Required touch points

- `src/inspectio/v3/settings.py`
- `src/inspectio/v3/persistence_writer/main.py`
- `src/inspectio/v3/persistence_writer/writer.py` (only if lock safety needed)
- `src/inspectio/v3/persistence_writer/metrics.py`
- relevant tests in `tests/unit/` + `tests/integration/`

## 4) Required settings

Add/wire:

- `INSPECTIO_V3_WRITER_PIPELINE_ENABLE` (bool, default `true`)
- `INSPECTIO_V3_WRITER_ACK_QUEUE_MAX_EVENTS` (int, `100..500000`, default `20000`)
- `INSPECTIO_V3_WRITER_FLUSH_LOOP_SLEEP_MS` (int, `1..1000`, default `10`)
- `INSPECTIO_V3_WRITER_RECEIVE_LOOP_PARALLELISM` (int, `1..4`, default `1`)

## 5) Pre-deploy test gate

Must pass before deployment:

1. pipeline task split tests (receive continues while ack backlog exists),
2. ack queue bound/backpressure tests,
3. no-ack-before-commit tests,
4. P12.4-P12.6 critical correctness suites.

## 6) Build and push

```bash
TAG=p12-9-iter6-$(date -u +%Y%m%d%H%M%S)
ECR=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3
docker buildx build --platform linux/amd64 -f deploy/docker/Dockerfile -t ${ECR}:${TAG} --push .
export IMG="${ECR}:${TAG}"
echo "IMG=${IMG}"
```

If image is already built, set it explicitly:

```bash
export IMG=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:REPLACE_WITH_EXISTING_TAG
```

## 7) Deploy image (excluding redis)

```bash
NS=inspectio
[ -n "${IMG:-}" ] || { echo "IMG is unset. Export IMG first."; exit 1; }

for d in $(kubectl -n ${NS} get deploy -o name | sed 's#deployment.apps/##'); do
  if [ "${d}" = "redis" ]; then
    continue
  fi
  kubectl -n ${NS} set image deployment/${d} "*=${IMG}"
done

for d in $(kubectl -n ${NS} get deploy -o name | sed 's#deployment.apps/##'); do
  kubectl -n ${NS} rollout status deployment/${d} --timeout=1200s
done
```

## 8) Artifact directory

```bash
ART=plans/v3_phases/artifacts/p12_9/iter-6
mkdir -p ${ART}
```

## 9) Benchmark protocol (hygiene-locked)

Use identical shape off/on:

- `--duration-sec 240 --concurrency 120 --batch 200`
- one success / zero failed attempts per job
- full stack recycle before each profile

Persist-off:

```bash
kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"false"}}'
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout restart deployment/${d}; done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout status deployment/${d} --timeout=1200s; done
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_start.txt
kubectl -n inspectio delete job inspectio-v3-p12-9-iter6-off --ignore-not-found
kubectl -n inspectio apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: inspectio-v3-p12-9-iter6-off
  namespace: inspectio
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: load
          image: ${IMG}
          command:
            - python
            - scripts/v3_sustained_admit.py
            - --api-base
            - http://inspectio-l1:8080
            - --duration-sec
            - "240"
            - --concurrency
            - "120"
            - --batch
            - "200"
            - --body-prefix
            - p12-9-iter6-off
EOF
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-iter6-off --timeout=920s
kubectl -n inspectio logs job/inspectio-v3-p12-9-iter6-off --all-pods=true > ${ART}/off-allpods.log
kubectl -n inspectio get job inspectio-v3-p12-9-iter6-off -o json > ${ART}/off_job_status.json
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_end.txt
```

Persist-on:

```bash
kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"true"}}'
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout restart deployment/${d}; done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout status deployment/${d} --timeout=1200s; done
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_start.txt
kubectl -n inspectio delete job inspectio-v3-p12-9-iter6-on --ignore-not-found
kubectl -n inspectio apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: inspectio-v3-p12-9-iter6-on
  namespace: inspectio
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: load
          image: ${IMG}
          command:
            - python
            - scripts/v3_sustained_admit.py
            - --api-base
            - http://inspectio-l1:8080
            - --duration-sec
            - "240"
            - --concurrency
            - "120"
            - --batch
            - "200"
            - --body-prefix
            - p12-9-iter6-on
EOF
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-iter6-on --timeout=920s
kubectl -n inspectio logs job/inspectio-v3-p12-9-iter6-on --all-pods=true > ${ART}/on-allpods.log
kubectl -n inspectio get job inspectio-v3-p12-9-iter6-on -o json > ${ART}/on_job_status.json
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_end.txt
```

## 10) Hygiene validator

```bash
python scripts/v3_p12_9_iter3_rerun_hygiene.py \
  --art-dir ${ART} \
  --image ${IMG} \
  --cluster-context "$(kubectl config current-context)" \
  --namespace inspectio \
  --region us-east-1 \
  --period-sec 60 \
  --preload-sec 60 \
  --tail-sec 120 \
  --stat Sum
```

## 11) Pipeline evidence capture (required)

Capture writer snapshots proving decoupled pipeline mode and queue metrics:

```bash
kubectl -n inspectio logs deploy/inspectio-persistence-writer --since=20m > ${ART}/writer-main.log || true
kubectl -n inspectio logs deploy/inspectio-persistence-writer-shard-0 --since=20m > ${ART}/writer-shard0.log || true
rg "writer_snapshot" ${ART}/writer-main.log ${ART}/writer-shard0.log > ${ART}/writer_snapshot_extract.json || true
```

If shard deployments are the primary writer topology, gather all shard logs similarly.

## 12) Required artifacts

- `off_start.txt`, `off_end.txt`
- `on_start.txt`, `on_end.txt`
- `off-allpods.log`, `on-allpods.log`
- `off_job_status.json`, `on_job_status.json`
- `sustain_summaries.json`
- `cw_metrics.json`
- `measurement_manifest.json`
- `writer_snapshot_extract.json`
- `ITER6_RESULTS.md`

## 13) Decision gate

Promote only if all true:

1. completion ratio >= `52.66%`
2. gain vs WS3.1 (`44.84%`) >= `+5.00pp`
3. no correctness regressions
4. no stability regressions
5. snapshot evidence shows decoupled mode + queue metrics present

Else: NO-GO, rollback to known-good image/config, document root cause in `ITER6_RESULTS.md`.
