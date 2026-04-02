# P12.9 Iteration 6 - Test Execution Spec (Handoff)

## Purpose

Run a deterministic, hygiene-locked validation of the Iteration 6 writer-pipeline fix and produce a complete evidence bundle for PROMOTE/NO-GO.

This spec is execution-only. Do not add code changes during this run.

This is the canonical execution source for Iteration 6 test runs.

---

## Scope Lock

In scope:

- Deploy current Iteration 6 image.
- Run persist-off and persist-on benchmark jobs with identical shape.
- Generate CloudWatch-based completion metrics with the existing hygiene script.
- Produce required artifacts and final decision report.

Out of scope:

- Any code edits.
- Any config experiments beyond `INSPECTIO_V3_PERSIST_EMIT_ENABLED` profile toggle.
- Any benchmark shape changes.

If scope is violated, invalidate run and restart.

---

## Required Inputs

1. Branch: `feat/v3-p12-9-tuning-iter-6-writer-pipeline`
2. Candidate image tag (must already be built):
   - format: `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:<tag>`
3. Cluster context:
   - `tzanshinnies@nitzan-inspectio.us-east-1.eksctl.io`
4. Namespace:
   - `inspectio`

---

## Required Environment Constants

```bash
NS=inspectio
CLUSTER=nitzan-inspectio
REGION=us-east-1
ART=plans/v3_phases/artifacts/p12_9/iter-6
IMG=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:REPLACE_WITH_ITER6_TAG
[ -n "${IMG:-}" ] || { echo "IMG is unset. Set IMG before running."; exit 1; }
```

Replace with a shell-safe tag value, for example:

```bash
IMG=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter6-20260402013331
```

If building in this run, set `IMG` immediately after build:

```bash
TAG=p12-9-iter6-$(date -u +%Y%m%d%H%M%S)
ECR=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3
IMG=${ECR}:${TAG}
docker buildx build --platform linux/amd64 -f deploy/docker/Dockerfile -t ${IMG} --push .
echo "IMG=${IMG}"
```

---

## Step 1 - Preflight

1. Confirm branch and clean intent:

```bash
git rev-parse --abbrev-ref HEAD
git status --short
```

2. Ensure cluster has worker nodes (if scaled to 0, scale up):

```bash
eksctl get nodegroup --cluster ${CLUSTER} --region ${REGION}
```

If desired capacity is 0, run:

```bash
eksctl scale nodegroup --cluster ${CLUSTER} --region ${REGION} --name ng-main --nodes 16 --nodes-min 2
```

Wait until nodes are ready:

```bash
kubectl get nodes
```

---

## Step 2 - Deploy Candidate Image

Apply image to all non-redis deployments:

```bash
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

Capture deployment snapshot:

```bash
mkdir -p ${ART}
kubectl -n ${NS} get deploy -o json > ${ART}/deployments_snapshot.json
kubectl -n ${NS} get configmap inspectio-v3-config -o json > ${ART}/configmap_snapshot.json
```

---

## Step 3 - Persist-Off Run

1. Toggle off:

```bash
kubectl -n ${NS} patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"false"}}'
```

2. Full stack recycle and wait:

```bash
for d in $(kubectl -n ${NS} get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n ${NS} rollout restart deployment/${d}; done
for d in $(kubectl -n ${NS} get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n ${NS} rollout status deployment/${d} --timeout=1200s; done
```

3. Run job:

```bash
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_start.txt
kubectl -n ${NS} delete job inspectio-v3-p12-9-iter6-off --ignore-not-found
kubectl -n ${NS} apply -f - <<EOF
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
kubectl -n ${NS} wait --for=condition=complete job/inspectio-v3-p12-9-iter6-off --timeout=920s
kubectl -n ${NS} logs job/inspectio-v3-p12-9-iter6-off --all-pods=true > ${ART}/off-allpods.log
kubectl -n ${NS} get job inspectio-v3-p12-9-iter6-off -o json > ${ART}/off_job_status.json
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_end.txt
```

4. Validate job status:

```bash
python - <<'PY'
import json, pathlib, sys
p=pathlib.Path("plans/v3_phases/artifacts/p12_9/iter-6/off_job_status.json")
s=json.loads(p.read_text()).get("status",{})
ok=(int(s.get("succeeded",0))==1 and int(s.get("failed",0))==0)
print({"succeeded":s.get("succeeded",0),"failed":s.get("failed",0),"valid":ok})
sys.exit(0 if ok else 1)
PY
```

If invalid, save `off_job_status_attemptN.json` + `off-allpods-attemptN.log`, then rerun Step 3.

---

## Step 4 - Persist-On Run

1. Toggle on:

```bash
kubectl -n ${NS} patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"true"}}'
```

2. Full stack recycle and wait:

```bash
for d in $(kubectl -n ${NS} get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n ${NS} rollout restart deployment/${d}; done
for d in $(kubectl -n ${NS} get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n ${NS} rollout status deployment/${d} --timeout=1200s; done
```

3. Run job:

```bash
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_start.txt
kubectl -n ${NS} delete job inspectio-v3-p12-9-iter6-on --ignore-not-found
kubectl -n ${NS} apply -f - <<EOF
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
kubectl -n ${NS} wait --for=condition=complete job/inspectio-v3-p12-9-iter6-on --timeout=920s
kubectl -n ${NS} logs job/inspectio-v3-p12-9-iter6-on --all-pods=true > ${ART}/on-allpods.log
kubectl -n ${NS} get job inspectio-v3-p12-9-iter6-on -o json > ${ART}/on_job_status.json
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_end.txt
```

4. Validate job status (same check as off, using `on_job_status.json`).

If invalid, save `on_job_status_attemptN.json` + `on-allpods-attemptN.log`, then rerun Step 4.

---

## Step 5 - Generate Metric Artifacts

```bash
python scripts/v3_p12_9_iter3_rerun_hygiene.py \
  --art-dir ${ART} \
  --image ${IMG} \
  --cluster-context "$(kubectl config current-context)" \
  --namespace ${NS} \
  --region ${REGION} \
  --period-sec 60 \
  --preload-sec 60 \
  --tail-sec 120 \
  --stat Sum
```

Expected generated files:

- `${ART}/sustain_summaries.json`
- `${ART}/cw_metrics.json`
- `${ART}/measurement_manifest.json`

---

## Step 6 - Capture Pipeline Evidence

```bash
for d in $(kubectl -n ${NS} get deploy -o name | sed 's#deployment.apps/##' | rg "inspectio-persistence-writer"); do
  kubectl -n ${NS} logs deploy/${d} --since=30m > ${ART}/${d}.log || true
done
rg "writer_snapshot" ${ART}/inspectio-persistence-writer*.log > ${ART}/writer_snapshot_extract.json || true
```

Minimum evidence requirement:

- snapshot lines contain `pipeline_mode` and queue metrics fields.

---

## Step 7 - Write Decision Report

Create `${ART}/ITER6_RESULTS.md` with sections:

1. Candidate image + branch.
2. Config under test (include pipeline settings values).
3. Admission summary (off/on).
4. Completion summary (off/on, ratio).
5. Hygiene validity checks (active periods, datapoint parity, job validity).
6. Pipeline evidence summary.
7. Decision:
   - PROMOTE iff:
     - completion ratio `>= 52.66`
     - gain vs WS3.1 baseline (`44.84`) `>= +5.00pp`
     - no correctness/stability regressions
     - pipeline evidence present
   - otherwise NO-GO.
8. Rollback action (if NO-GO).

---

## Step 8 - Artifact Completeness Check (must pass)

```bash
python - <<'PY'
from pathlib import Path
art = Path("plans/v3_phases/artifacts/p12_9/iter-6")
required = [
  "off_start.txt","off_end.txt","on_start.txt","on_end.txt",
  "off-allpods.log","on-allpods.log",
  "off_job_status.json","on_job_status.json",
  "sustain_summaries.json","cw_metrics.json","measurement_manifest.json",
  "writer_snapshot_extract.json","ITER6_RESULTS.md",
]
missing=[p for p in required if not (art/p).exists()]
print({"missing": missing, "ok": not missing})
raise SystemExit(1 if missing else 0)
PY
```

---

## Step 9 - Rollback (if NO-GO)

```bash
ROLLBACK_IMG=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter2-20260331224309
for d in $(kubectl -n ${NS} get deploy -o name | sed 's#deployment.apps/##'); do
  if [ "${d}" = "redis" ]; then
    continue
  fi
  kubectl -n ${NS} set image deployment/${d} "*=${ROLLBACK_IMG}"
done
for d in $(kubectl -n ${NS} get deploy -o name | sed 's#deployment.apps/##'); do
  kubectl -n ${NS} rollout status deployment/${d} --timeout=1200s
done
```

---

## Step 10 - Cost Safety (end of run)

```bash
eksctl scale nodegroup --cluster ${CLUSTER} --region ${REGION} --name ng-main --nodes 0 --nodes-min 0
```

Verify no worker nodes remain.
