# P12.9 WS3.2 Iteration-4 — SE Handoff Brief

This brief is the execution runbook for Iteration 4 only.

## 1) Scope lock

Allowed:

- Checkpoint write cadence control in persistence writer.
- Additive checkpoint-cost metrics.
- Tests and benchmark artifacts required by the spec.

Not allowed:

- Flush policy tuning.
- Ack strategy tuning.
- Retry/backoff tuning.
- Schema/replay/API changes.

If non-scope changes are included, Iteration 4 evidence is invalid.

## 2) Branch and baseline

```bash
git checkout -b feat/v3-p12-9-tuning-iter-4-checkpoint-cadence
```

Use Iteration 3 candidate image behavior as baseline comparator in results:

- `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter3-20260401084203`

## 3) Required code touch points

- `src/inspectio/v3/settings.py`
- `src/inspectio/v3/persistence_writer/*` (checkpoint cadence only)
- `src/inspectio/v3/persistence_writer/metrics.py`
- corresponding tests in `tests/unit/` and `tests/integration/`

## 4) Required setting contract

If not already present, add:

- `INSPECTIO_V3_PERSISTENCE_CHECKPOINT_EVERY_N_FLUSHES`
  - type: int
  - default: `1`
  - bounds: `1..20`

Semantics:

- `1` = checkpoint every flush (existing behavior).
- `N>1` = checkpoint every N flushes, while preserving segment-before-checkpoint safety.

## 5) Test gate before deploy

Must pass before any AWS benchmark:

1. Unit tests for cadence logic (`N=1`, `N>1`, bounds).
2. Unit/integration tests proving segment-before-checkpoint contract.
3. Replay correctness checks for sparse checkpoints.
4. Existing P12.4-P12.6 critical correctness suites.

## 6) Build and push image

```bash
TAG=p12-9-iter4-$(date -u +%Y%m%d%H%M%S)
ECR=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3
docker buildx build --platform linux/amd64 -f deploy/docker/Dockerfile -t ${ECR}:${TAG} --push .
echo "${ECR}:${TAG}"
```

## 7) Deploy image to inspectio workloads

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
ART=plans/v3_phases/artifacts/p12_9/iter-4
mkdir -p ${ART}
```

## 9) Benchmark protocol (hygiene-locked)

Use identical shape for off/on:

- `--duration-sec 240 --concurrency 120 --batch 200`
- one job success, zero failed attempts
- full stack recycle before each profile

Persist-off:

```bash
kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"false"}}'
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout restart deployment/${d}; done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout status deployment/${d} --timeout=1200s; done

date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_start.txt
kubectl -n inspectio delete job inspectio-v3-p12-9-iter4-off --ignore-not-found
kubectl -n inspectio apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: inspectio-v3-p12-9-iter4-off
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
            - p12-9-iter4-off
EOF
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-iter4-off --timeout=920s
kubectl -n inspectio logs job/inspectio-v3-p12-9-iter4-off --all-pods=true > ${ART}/off-allpods.log
kubectl -n inspectio get job inspectio-v3-p12-9-iter4-off -o json > ${ART}/off_job_status.json
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_end.txt
```

Persist-on:

```bash
kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"true"}}'
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout restart deployment/${d}; done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout status deployment/${d} --timeout=1200s; done

date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_start.txt
kubectl -n inspectio delete job inspectio-v3-p12-9-iter4-on --ignore-not-found
kubectl -n inspectio apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: inspectio-v3-p12-9-iter4-on
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
            - p12-9-iter4-on
EOF
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-iter4-on --timeout=920s
kubectl -n inspectio logs job/inspectio-v3-p12-9-iter4-on --all-pods=true > ${ART}/on-allpods.log
kubectl -n inspectio get job inspectio-v3-p12-9-iter4-on -o json > ${ART}/on_job_status.json
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_end.txt
```

## 10) Rerun hygiene validator

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

Then copy:

```bash
cp ${ART}/measurement_manifest.json ${ART}/measurement_manifest_raw.json
cp ${ART}/cw_metrics.json ${ART}/cw_metrics_raw.json
```

## 11) Required artifacts to commit

- `off_start.txt`, `off_end.txt`
- `on_start.txt`, `on_end.txt`
- `off-allpods.log`, `on-allpods.log`
- `off_job_status.json`, `on_job_status.json`
- `sustain_summaries.json`
- `cw_metrics.json`
- `measurement_manifest.json`
- `ITER4_RESULTS.md`

## 12) Decision gate (Iteration 4)

Promote only if all pass:

1. completion ratio >= `52.66%`
2. gain vs WS3.1 (`44.84%`) is >= `+5.00pp`
3. no correctness regressions
4. no stability regressions

Else: NO-GO + rollback to last known good image/config and document in `ITER4_RESULTS.md`.
