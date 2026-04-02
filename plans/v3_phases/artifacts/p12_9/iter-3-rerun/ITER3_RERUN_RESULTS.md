# P12.9 WS3.1 Iteration-3 Rerun Results

## Scope

WS3.1 rerun executes measurement-hygiene fixes only (no tuning algorithm changes) for Iteration 3.

## Frozen candidate under test

- image: `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter3-20260401084203`
- benchmark shape (unchanged):
  - `duration-sec=240`
  - `concurrency=120`
  - `batch=200`
- queue topology: `inspectio-v3-send-0..7`

## Run validity checks (R2-R5)

From `cw_metrics.json` and job status artifacts:

- off job single-success/zero-failed: `PASS` (`succeeded=1`, `failed=0`)
- on job single-success/zero-failed: `PASS` (`succeeded=1`, `failed=0`)
- symmetric window policy: `PASS` (same preload/tail for both profiles)
  - preload: `60s`
  - tail: `120s`
- active CloudWatch periods: `PASS`
  - off active periods: `6` (`>=5`)
  - on active periods: `6` (`>=5`)
- datapoint parity: `PASS`
  - off datapoints: `7`
  - on datapoints: `7`
  - absolute difference: `0` (`<=1`)
- CloudWatch period/stat policy: `PASS` (`60s`, `Sum`)

## Completion ratio and decision (R6)

- off combined avg completion RPS: `7771.82`
- on combined avg completion RPS: `3485.17`
- completion ratio (on/off, combined_avg_rps): `44.84%`
- Iteration-3 promotion threshold: `52.66%`

Decision: **NO-GO** (`44.84% < 52.66%`).

Rollback executed after rerun decision:

- rollback image:
  `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter2-20260331224309`
- all non-redis deployments rolled out successfully on rollback image.

## Commands executed (explicit)

```bash
# Freeze candidate image
NS=inspectio
IMG=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter3-20260401084203
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

```bash
# Persist-off profile (full recycle first)
ART=plans/v3_phases/artifacts/p12_9/iter-3-rerun
kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"false"}}'
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout restart deployment/${d}; done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout status deployment/${d} --timeout=1200s; done
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_start.txt
kubectl -n inspectio delete job inspectio-v3-p12-9-iter3-rerun-off --ignore-not-found
kubectl -n inspectio apply -f /tmp/iter3-rerun-off-job.yaml
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-iter3-rerun-off --timeout=920s
kubectl -n inspectio logs job/inspectio-v3-p12-9-iter3-rerun-off --all-pods=true > ${ART}/off-allpods.log
kubectl -n inspectio get job inspectio-v3-p12-9-iter3-rerun-off -o json > ${ART}/off_job_status.json
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_end.txt
```

```bash
# Persist-on profile (full recycle first)
kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"true"}}'
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout restart deployment/${d}; done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout status deployment/${d} --timeout=1200s; done
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_start.txt
kubectl -n inspectio delete job inspectio-v3-p12-9-iter3-rerun-on --ignore-not-found
kubectl -n inspectio apply -f /tmp/iter3-rerun-on-job.yaml
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-iter3-rerun-on --timeout=920s
kubectl -n inspectio logs job/inspectio-v3-p12-9-iter3-rerun-on --all-pods=true > ${ART}/on-allpods.log
kubectl -n inspectio get job inspectio-v3-p12-9-iter3-rerun-on -o json > ${ART}/on_job_status.json
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_end.txt
```

```bash
# Rerun hygiene validation + metric generation
python scripts/v3_p12_9_iter3_rerun_hygiene.py \
  --art-dir plans/v3_phases/artifacts/p12_9/iter-3-rerun \
  --image 194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:p12-9-iter3-20260401084203 \
  --cluster-context tzanshinnies@nitzan-inspectio.us-east-1.eksctl.io \
  --namespace inspectio \
  --region us-east-1 \
  --period-sec 60 \
  --preload-sec 60 \
  --tail-sec 120 \
  --stat Sum
```

## Artifacts

- `off_start.txt`, `off_end.txt`
- `on_start.txt`, `on_end.txt`
- `off-allpods.log`, `on-allpods.log`
- `sustain_summaries.json`
- `cw_metrics.json`
- `measurement_manifest.json`
