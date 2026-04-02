# P12.9 WS3.3 Iteration-5 — SE Handoff Brief

Use this runbook for Iteration 5 only.

## 1) Scope lock

Allowed:

- Flush cadence/occupancy tuning.
- Additive flush-efficiency metrics.
- Required tests and benchmark artifacts.

Not allowed:

- Ack tuning.
- Checkpoint cadence tuning.
- Retry/backoff tuning.
- Schema/replay/API changes.

## 2) Branch

```bash
git checkout -b feat/v3-p12-9-tuning-iter-5-flush-cadence
```

## 3) Required files (expected)

- `src/inspectio/v3/settings.py`
- `src/inspectio/v3/persistence_writer/*` (flush logic only)
- `src/inspectio/v3/persistence_writer/metrics.py`
- tests in `tests/unit/` and `tests/integration/`

## 4) Flush control contract

Use explicit settings (or mapped equivalents):

- `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_INTERVAL_MS`
- `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS`

Document exact before/after values in `ITER5_RESULTS.md`.

## 5) Pre-deploy test gate

Must pass:

1. Unit tests for low/high ingest flush behavior.
2. Unit tests for settings bounds/validation.
3. P12.4-P12.6 critical correctness suites.

## 6) Build and push

```bash
TAG=p12-9-iter5-$(date -u +%Y%m%d%H%M%S)
ECR=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3
docker buildx build --platform linux/amd64 -f deploy/docker/Dockerfile -t ${ECR}:${TAG} --push .
echo "${ECR}:${TAG}"
```

## 7) Deploy to inspectio (excluding redis)

```bash
NS=inspectio
IMG=<paste-built-image>

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

## 8) Artifact folder

```bash
ART=plans/v3_phases/artifacts/p12_9/iter-5
mkdir -p ${ART}
```

## 9) Hygiene-locked benchmarks

Shape for both profiles:

- `--duration-sec 240 --concurrency 120 --batch 200`
- one success / zero failed attempts required

Persist-off:

```bash
kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"false"}}'
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout restart deployment/${d}; done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout status deployment/${d} --timeout=1200s; done
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_start.txt
kubectl -n inspectio delete job inspectio-v3-p12-9-iter5-off --ignore-not-found
kubectl -n inspectio apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: inspectio-v3-p12-9-iter5-off
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
            - p12-9-iter5-off
EOF
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-iter5-off --timeout=920s
kubectl -n inspectio logs job/inspectio-v3-p12-9-iter5-off --all-pods=true > ${ART}/off-allpods.log
kubectl -n inspectio get job inspectio-v3-p12-9-iter5-off -o json > ${ART}/off_job_status.json
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_end.txt
```

Persist-on:

```bash
kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"true"}}'
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout restart deployment/${d}; done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout status deployment/${d} --timeout=1200s; done
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_start.txt
kubectl -n inspectio delete job inspectio-v3-p12-9-iter5-on --ignore-not-found
kubectl -n inspectio apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: inspectio-v3-p12-9-iter5-on
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
            - p12-9-iter5-on
EOF
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-iter5-on --timeout=920s
kubectl -n inspectio logs job/inspectio-v3-p12-9-iter5-on --all-pods=true > ${ART}/on-allpods.log
kubectl -n inspectio get job inspectio-v3-p12-9-iter5-on -o json > ${ART}/on_job_status.json
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

## 11) Required artifacts

- `off_start.txt`, `off_end.txt`
- `on_start.txt`, `on_end.txt`
- `off-allpods.log`, `on-allpods.log`
- `off_job_status.json`, `on_job_status.json`
- `sustain_summaries.json`
- `cw_metrics.json`
- `measurement_manifest.json`
- `ITER5_RESULTS.md`

## 12) Decision gate

Promote Iteration 5 only if all true:

1. completion ratio >= `52.66%`
2. gain vs WS3.1 (`44.84%`) >= `+5.00pp`
3. no correctness regressions
4. no stability regressions

Else mark NO-GO, rollback, and document exact failure reason in `ITER5_RESULTS.md`.
