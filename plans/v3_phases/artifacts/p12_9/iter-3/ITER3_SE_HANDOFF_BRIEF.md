# P12.9 WS3 Iteration 3 — SE Handoff Brief

Use this as the implementation runbook for Iteration 3 only.

## 1) Scope lock (do not violate)

Allowed:

- Bounded ack delete concurrency in persistence transport consumer.
- Flush occupancy/interval tuning in persistence writer hot path.
- Additive writer metrics for ack/flush diagnosis.

Not allowed:

- Schema/event contract changes.
- Replay/bootstrap/checkpoint semantic changes.
- API behavior changes.
- Mixing Iteration 4 experiments in this PR.

## 2) Files expected to change

- `src/inspectio/v3/persistence_transport/sqs_consumer.py`
- `src/inspectio/v3/persistence_writer/main.py` (or local writer internals only)
- `src/inspectio/v3/persistence_writer/metrics.py`
- `src/inspectio/v3/settings.py`
- `tests/unit/` for ack/flush/metrics behavior

## 3) Required config knobs

Use existing names if already present; otherwise add equivalent settings with bounds:

- `INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY` (`1..8`, default `2`)
- `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS` (`1..writer_flush_batch_max`)
- `INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_INTERVAL_MS` (document before/after if changed)

## 4) Test gate before deploy

Must pass:

1. Unit tests for bounded `ack_many` concurrency and retry-safe receipt handling.
2. Unit tests for flush trigger behavior (low/high ingest, no starvation).
3. Existing writer/observability unit tests.
4. Persistence correctness suites for P12.4-P12.6 critical paths.

## 5) Branch and image

```bash
git checkout -b feat/v3-p12-9-tuning-iter-3
```

After code/tests are done:

```bash
TAG=p12-9-iter3-$(date -u +%Y%m%d%H%M%S)
ECR=194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3
docker buildx build --platform linux/amd64 -f deploy/docker/Dockerfile -t ${ECR}:${TAG} --push .
echo "${ECR}:${TAG}"
```

## 6) Deploy (same image to all app deployments, keep redis image unchanged)

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
  kubectl -n ${NS} rollout status deployment/${d} --timeout=900s
done
```

## 7) Benchmark protocol (must match Iteration 2 shape)

Artifact folder:

```bash
ART=plans/v3_phases/artifacts/p12_9/iter-3
mkdir -p ${ART}
```

Persist-off run:

```bash
kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"false"}}'
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout restart deployment/$d; done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout status deployment/$d --timeout=900s; done

date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_start.txt
kubectl -n inspectio delete job inspectio-v3-p12-9-iter3-off --ignore-not-found
kubectl -n inspectio create job inspectio-v3-p12-9-iter3-off --image=${IMG} -- \
  python scripts/v3_sustained_admit.py --api-base http://inspectio-l1:8080 --duration-sec 240 --concurrency 120 --batch 200 --body-prefix p12-9-iter3-off
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-iter3-off --timeout=920s
kubectl -n inspectio logs job/inspectio-v3-p12-9-iter3-off --all-pods=true > ${ART}/off-allpods.log
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/off_end.txt
```

Persist-on run:

```bash
kubectl -n inspectio patch configmap inspectio-v3-config --type merge -p '{"data":{"INSPECTIO_V3_PERSIST_EMIT_ENABLED":"true"}}'
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout restart deployment/$d; done
for d in $(kubectl -n inspectio get deploy -o name | sed 's#deployment.apps/##'); do kubectl -n inspectio rollout status deployment/$d --timeout=900s; done

date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_start.txt
kubectl -n inspectio delete job inspectio-v3-p12-9-iter3-on --ignore-not-found
kubectl -n inspectio create job inspectio-v3-p12-9-iter3-on --image=${IMG} -- \
  python scripts/v3_sustained_admit.py --api-base http://inspectio-l1:8080 --duration-sec 240 --concurrency 120 --batch 200 --body-prefix p12-9-iter3-on
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-p12-9-iter3-on --timeout=920s
kubectl -n inspectio logs job/inspectio-v3-p12-9-iter3-on --all-pods=true > ${ART}/on-allpods.log
date -u +%Y-%m-%dT%H:%M:%SZ > ${ART}/on_end.txt
```

## 8) Required artifacts to commit

- `${ART}/off-allpods.log`
- `${ART}/on-allpods.log`
- `${ART}/off_start.txt`
- `${ART}/off_end.txt`
- `${ART}/on_start.txt`
- `${ART}/on_end.txt`
- `${ART}/sustain_summaries.json`
- `${ART}/cw_metrics.json`
- `${ART}/ITER3_RESULTS.md`

## 9) Decision gate

Promote Iteration 3 only if all pass:

1. Completion ratio `>= 52.66%`
2. Improvement vs Iteration 2 `>= +5.00pp`
3. No correctness regression
4. No stability regression

Otherwise rollback to previous known-good image/config and record the no-go outcome in `ITER3_RESULTS.md`.
