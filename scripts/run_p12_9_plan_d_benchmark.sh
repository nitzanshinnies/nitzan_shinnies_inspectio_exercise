#!/usr/bin/env bash
# P12.9 Plan D — EKS persist-off / persist-on benchmark (automation).
# Normative procedure: plans/v3_phases/P12_9_ITER6_TEST_EXECUTION_SPEC.md
# Checklist and iter-N naming: plans/v3_phases/P12_9_AI_SE_PLAN_D_EKS_BENCHMARK_EXECUTION.md
#
# Required env:
#   ITER — iteration number for job names and default ART (e.g. 7 → iter-7, iter7-off job)
#   IMG  — full ECR image ref used by Jobs and (unless SKIP_DEPLOY=1) all non-redis Deployments
# Optional env:
#   NS=inspectio  CLUSTER=nitzan-inspectio  REGION=us-east-1
#   ART — override artifact directory (default: plans/v3_phases/artifacts/p12_9/iter-${ITER})
#   RESULTS — decision markdown filename inside ART (default: ITER${ITER}_RESULTS.md)
#   SKIP_DEPLOY=1 — skip Step 2 image rollout (cluster already on IMG)
#   COST_SAFETY=1 — after run, scale nodegroup to 0 (Plan D Task D.10)
#
# Does not write ITERn_RESULTS.md (human PROMOTE/NO-GO + tables). After jobs + hygiene,
# complete Plan D.8 manually, then run the completeness block at the bottom of this file.

set -euo pipefail

ITER="${ITER:?set ITER (e.g. 7)}"
IMG="${IMG:?set IMG to full ECR image}"
NS="${NS:-inspectio}"
CLUSTER="${CLUSTER:-nitzan-inspectio}"
REGION="${REGION:-us-east-1}"
ART="${ART:-plans/v3_phases/artifacts/p12_9/iter-${ITER}}"
RESULTS="${RESULTS:-ITER${ITER}_RESULTS.md}"
JOB_OFF="inspectio-v3-p12-9-iter${ITER}-off"
JOB_ON="inspectio-v3-p12-9-iter${ITER}-on"
PREFIX_OFF="p12-9-iter${ITER}-off"
PREFIX_ON="p12-9-iter${ITER}-on"
SKIP_DEPLOY="${SKIP_DEPLOY:-0}"
COST_SAFETY="${COST_SAFETY:-0}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "== Plan D preflight: context / nodes =="
kubectl config current-context || true
eksctl get nodegroup --cluster "${CLUSTER}" --region "${REGION}" || true
kubectl get nodes

if [[ "${SKIP_DEPLOY}" != "1" ]]; then
  echo "== Deploy candidate image to non-redis Deployments =="
  for d in $(kubectl -n "${NS}" get deploy -o name | sed 's#deployment.apps/##'); do
    if [[ "${d}" == "redis" ]]; then
      continue
    fi
    kubectl -n "${NS}" set image "deployment/${d}" "*=${IMG}"
  done
  for d in $(kubectl -n "${NS}" get deploy -o name | sed 's#deployment.apps/##'); do
    kubectl -n "${NS}" rollout status "deployment/${d}" --timeout=1200s
  done
fi

mkdir -p "${ART}"
kubectl -n "${NS}" get deploy -o json > "${ART}/deployments_snapshot.json"
kubectl -n "${NS}" get configmap inspectio-v3-config -o json > "${ART}/configmap_snapshot.json"

_validate_job_json() {
  local json_path="$1"
  python3 - <<'PY' "${json_path}"
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
s = json.loads(p.read_text()).get("status", {})
ok = int(s.get("succeeded", 0)) == 1 and int(s.get("failed", 0)) == 0
print({"succeeded": s.get("succeeded", 0), "failed": s.get("failed", 0), "valid": ok})
sys.exit(0 if ok else 1)
PY
}

_run_leg() {
  local persist_enabled="$1"
  local job_name="$2"
  local body_prefix="$3"
  local start_file="$4"
  local end_file="$5"
  local log_file="$6"
  local status_file="$7"

  kubectl -n "${NS}" patch configmap inspectio-v3-config --type merge \
    -p "{\"data\":{\"INSPECTIO_V3_PERSIST_EMIT_ENABLED\":\"${persist_enabled}\"}}"
  for d in $(kubectl -n "${NS}" get deploy -o name | sed 's#deployment.apps/##'); do
    kubectl -n "${NS}" rollout restart "deployment/${d}"
  done
  for d in $(kubectl -n "${NS}" get deploy -o name | sed 's#deployment.apps/##'); do
    kubectl -n "${NS}" rollout status "deployment/${d}" --timeout=1200s
  done

  date -u +%Y-%m-%dT%H:%M:%SZ > "${ART}/${start_file}"
  kubectl -n "${NS}" delete job "${job_name}" --ignore-not-found
  kubectl -n "${NS}" apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
  namespace: ${NS}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: inspectio-app
      imagePullPolicy: Always
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
            - ${body_prefix}
EOF
  kubectl -n "${NS}" wait --for=condition=complete "job/${job_name}" --timeout=920s
  kubectl -n "${NS}" logs "job/${job_name}" --all-pods=true > "${ART}/${log_file}"
  kubectl -n "${NS}" get job "${job_name}" -o json > "${ART}/${status_file}"
  date -u +%Y-%m-%dT%H:%M:%SZ > "${ART}/${end_file}"
}

echo "== Persist-off leg =="
_run_leg "false" "${JOB_OFF}" "${PREFIX_OFF}" "off_start.txt" "off_end.txt" \
  "off-allpods.log" "off_job_status.json"
_validate_job_json "${ART}/off_job_status.json"

echo "== Persist-on leg =="
_run_leg "true" "${JOB_ON}" "${PREFIX_ON}" "on_start.txt" "on_end.txt" \
  "on-allpods.log" "on_job_status.json"
_validate_job_json "${ART}/on_job_status.json"

echo "== Hygiene (CloudWatch) =="
python3 scripts/v3_p12_9_iter3_rerun_hygiene.py \
  --art-dir "${ART}" \
  --image "${IMG}" \
  --cluster-context "$(kubectl config current-context)" \
  --namespace "${NS}" \
  --region "${REGION}" \
  --period-sec 60 \
  --preload-sec 60 \
  --tail-sec 120 \
  --stat Sum

echo "== Writer pipeline evidence =="
for d in $(kubectl -n "${NS}" get deploy -o name | sed 's#deployment.apps/##' | grep inspectio-persistence-writer || true); do
  kubectl -n "${NS}" logs "deploy/${d}" --since=45m > "${ART}/${d}.log" 2>/dev/null || true
done
if command -v rg >/dev/null 2>&1; then
  rg "writer_snapshot" "${ART}"/inspectio-persistence-writer*.log > "${ART}/writer_snapshot_extract.json" || true
else
  grep -h "writer_snapshot" "${ART}"/inspectio-persistence-writer*.log 2>/dev/null > "${ART}/writer_snapshot_extract.json" || true
fi

echo "== Completeness (add ${RESULTS} via Plan D.8; set STRICT_ARTIFACTS=1 to fail on gaps) =="
export ART
export RESULTS
export STRICT_ARTIFACTS="${STRICT_ARTIFACTS:-0}"
python3 - <<'PY'
import os
import sys
from pathlib import Path

art = Path(os.environ["ART"])
results = os.environ["RESULTS"]
required = [
    "off_start.txt",
    "off_end.txt",
    "on_start.txt",
    "on_end.txt",
    "off-allpods.log",
    "on-allpods.log",
    "off_job_status.json",
    "on_job_status.json",
    "sustain_summaries.json",
    "cw_metrics.json",
    "measurement_manifest.json",
    "writer_snapshot_extract.json",
    results,
]
missing = [p for p in required if not (art / p).exists()]
print({"missing": missing, "ok": not missing})
strict = os.environ.get("STRICT_ARTIFACTS", "0") == "1"
sys.exit(1 if missing and strict else 0)
PY

if [[ "${COST_SAFETY}" == "1" ]]; then
  echo "== Cost safety: scale nodegroup to 0 =="
  eksctl scale nodegroup --cluster "${CLUSTER}" --region "${REGION}" --name ng-main --nodes 0 --nodes-min 0
fi

echo "Done. Write ${ART}/${RESULTS} (Plan D.8) if not already present, then re-run completeness."
