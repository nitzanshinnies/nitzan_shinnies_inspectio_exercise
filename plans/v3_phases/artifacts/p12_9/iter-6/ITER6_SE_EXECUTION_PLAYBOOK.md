# P12.9 WS3.4 Iteration-6 — SE Execution Playbook (Strict)

Use this document as the authoritative execution checklist for Iteration 6 completion.
Do not skip steps. Do not change workload shape or acceptance gates.

---

## 0) Mission

Finalize Iteration 6 by producing a complete, hygiene-valid benchmark bundle for the writer pipeline repair already implemented in code.

This playbook assumes code changes are present and unit/integration tests are green locally.

---

## 1) Non-negotiable constraints

1. No additional tuning changes in this pass.
2. No schema/replay/API behavior changes.
3. Full stack recycle before each profile run.
4. Off/on benchmark shape must be identical.
5. One successful job and zero failed attempts per profile.

If any constraint is violated, rerun from the affected profile.

---

## 2) Branch hygiene

```bash
git checkout feat/v3-p12-9-tuning-iter-6-writer-pipeline
git status --short
```

Expected: only Iteration-6 related changes.

---

## 3) Required test gate (must pass)

```bash
pytest -q \
  tests/unit/test_v3_persistence_writer_main_observability.py \
  tests/unit/test_v3_settings_persistence_writer.py \
  tests/integration/test_v3_persistence_writer_fake_flow.py
```

If this fails, stop and fix before any deploy.

---

## 4) Build and push image

```bash
TAG=p12-9-iter6-$(date -u +%Y%m%d%H%M%S)
ECR=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3
IMG=${ECR}:${TAG}
docker buildx build --platform linux/amd64 -f deploy/docker/Dockerfile -t ${IMG} --push .
echo "${IMG}"
```

Record `${IMG}` for results.

---

## 5) Scale cluster for benchmark (if currently at 0)

```bash
eksctl scale nodegroup \
  --cluster nitzan-inspectio \
  --region us-east-1 \
  --name ng-main \
  --nodes 16 \
  --nodes-min 2
```

Wait until nodes are ready and deployments can schedule.

---

## 6) Deploy image (all app deployments, exclude redis)

```bash
NS=inspectio
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

---

## 7) Prepare artifact directory

```bash
ART=plans/v3_phases/artifacts/p12_9/iter-6
mkdir -p ${ART}
```

---

## 8) Persist-off run (strict)

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

Validation:

```bash
python - <<'PY'
import json, pathlib
j=json.loads(pathlib.Path("plans/v3_phases/artifacts/p12_9/iter-6/off_job_status.json").read_text())
s=j.get("status",{})
print({"succeeded":s.get("succeeded",0),"failed":s.get("failed",0)})
PY
```

Must print `succeeded=1`, `failed=0`.

---

## 9) Persist-on run (strict)

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

Validation must also be `succeeded=1`, `failed=0`.

---

## 10) Generate metric artifacts (hygiene validator)

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

This must produce:

- `sustain_summaries.json`
- `cw_metrics.json`
- `measurement_manifest.json`

---

## 11) Capture pipeline evidence (mandatory)

Collect all writer deployments (including shard writers) from the run window:

```bash
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##' | rg "inspectio-persistence-writer"); do
  kubectl -n inspectio logs deploy/${d} --since=30m > ${ART}/${d}.log || true
done
rg "writer_snapshot" ${ART}/inspectio-persistence-writer*.log > ${ART}/writer_snapshot_extract.json || true
```

`writer_snapshot_extract.json` must show:

- `pipeline_mode = decoupled_v1`
- non-null queue metrics (`ack_queue_depth_*`, `flush_loop_*`, `receive_loop_*`)

---

## 12) Write `ITER6_RESULTS.md` (required template)

Include all sections:

1. Image/branch under test.
2. Config deltas used (all new pipeline knobs).
3. Admission off/on summary.
4. Completion off/on summary and ratio.
5. Gate evaluation:
   - ratio >= 52.66
   - gain vs 44.84 >= +5.00pp
   - correctness/stability status
   - pipeline evidence status
6. PROMOTE or NO-GO.
7. Rollback action taken (if NO-GO).

---

## 13) Artifact completeness checklist (must all exist)

- `off_start.txt`, `off_end.txt`
- `on_start.txt`, `on_end.txt`
- `off-allpods.log`, `on-allpods.log`
- `off_job_status.json`, `on_job_status.json`
- `sustain_summaries.json`
- `cw_metrics.json`
- `measurement_manifest.json`
- `writer_snapshot_extract.json`
- `ITER6_RESULTS.md`

---

## 14) If NO-GO: required rollback

```bash
ROLLBACK_IMG=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter2-20260331224309
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do
  if [ "${d}" = "redis" ]; then
    continue
  fi
  kubectl -n inspectio set image deployment/${d} "*=${ROLLBACK_IMG}"
done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do
  kubectl -n inspectio rollout status deployment/${d} --timeout=1200s
done
```

Record rollback in `ITER6_RESULTS.md`.

---

## 15) Post-run cost safety

After artifacts are committed:

```bash
eksctl scale nodegroup \
  --cluster nitzan-inspectio \
  --region us-east-1 \
  --name ng-main \
  --nodes 0 \
  --nodes-min 0
```

Verify node count reaches zero.
