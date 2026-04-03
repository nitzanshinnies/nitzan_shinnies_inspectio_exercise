# Inspectio v3 — Kubernetes (EKS)

Manifests for **namespace `inspectio`**: Redis (dev/in-cluster), **L2** (`inspectio-api`, ≥2 replicas), **expander**, **send worker(s)**, **persistence-writer**, **L1** edge (same container image as L2, different command). **LocalStack is not used here** — point `INSPECTIO_V3_*_QUEUE_URL` values at **real AWS SQS** standard queues.

See **`plans/v3_phases/P6_KUBERNETES.md`**, workspace rule **`inspectio-eks-agent-executes-deploy`**, and **`plans/V3_ASYNC_PIPELINE_IMPLEMENTATION_PLAN.md`**.

## Prerequisites

- Image built from **`deploy/docker/Dockerfile`** and pushed to your registry (e.g. ECR).
- SQS queues: one **bulk** queue and **`K`** **send** queues (`INSPECTIO_V3_SEND_SHARD_COUNT` must match **`INSPECTIO_V3_SEND_QUEUE_URLS`**).
- **IRSA** (recommended): set `eks.amazonaws.com/role-arn` on **`ServiceAccount/inspectio-app`** to a role that can `sqs:ReceiveMessage`, `SendMessage`, `DeleteMessage`, `GetQueueUrl` (and send to optional persist queue if enabled).
- **Redis**: in-cluster Deployment here is for exercise/smoke; production often uses **ElastiCache** — set **`REDIS_URL`** / **`INSPECTIO_REDIS_URL`** in a ConfigMap or Secret to that endpoint.

## Apply order

1. Edit **`configmap.yaml`**: replace `REPLACE_WITH_SQS_*` placeholders; align **`INSPECTIO_V3_SEND_SHARD_COUNT`** with the number of send URLs. **`INSPECTIO_V3_SEND_QUEUE_URLS`** must be a **JSON array** string (e.g. `'["https://sqs.../shard-0","https://.../shard-1"]'`) so **`V3ExpanderSettings`** can parse it from Kubernetes env. For P12.2/P12.8 transport handoff, set **`INSPECTIO_V3_PERSIST_EMIT_ENABLED=true`** and either fill single queue envs (**`..._QUEUE_URL`**, optional **`..._DLQ_URL`**) or shard list envs (**`..._SHARD_COUNT`** + **`..._QUEUE_URLS`** + optional **`..._DLQ_URLS`**).
2. Edit **`serviceaccount.yaml`**: set the real **IRSA** role ARN (or drop the annotation if the node role suffices).
3. (Optional) Create **`inspectio-v3-secrets`** for static AWS keys — see **`secret-aws.example.yaml`**. Deployments use **`optional: true`** so IRSA-only clusters do not require this Secret.
4. Apply:

```bash
kubectl apply -k deploy/kubernetes/
```

Or apply files individually in dependency order: **namespace** → **serviceaccount** → **redis** → **configmap** → workloads.

## Rolling out a new image

Prefer **`kubectl set image`** (avoids fighting immutable **Deployment** `spec.selector`):

```bash
kubectl -n inspectio set image deployment/inspectio-api api=ACCOUNT.dkr.ecr.REGION.amazonaws.com/inspectio-v3:TAG
kubectl -n inspectio set image deployment/inspectio-expander expander=...
kubectl -n inspectio set image deployment/inspectio-worker worker=...
kubectl -n inspectio set image deployment/inspectio-l1 l1=...
kubectl -n inspectio set image deployment/inspectio-persistence-writer persistence-writer=...
kubectl -n inspectio rollout status deployment/inspectio-api --timeout=120s
kubectl -n inspectio rollout status deployment/inspectio-l1 --timeout=120s
```

**ConfigMap-only changes** (queue URLs, `K`, Redis URL): `kubectl apply -f deploy/kubernetes/configmap.yaml` then **restart** pods that read it (rollout restart Deployments).

## Multi-shard workers (`K` > 1)

Duplicate **`inspectio-worker.yaml`** per shard (e.g. `inspectio-worker-1.yaml`) with a **unique** `metadata.name` and **`INSPECTIO_V3_WORKER_SEND_QUEUE_URL`** for that shard’s queue. Keep **`INSPECTIO_V3_SEND_QUEUE_URLS`** and **`INSPECTIO_V3_SEND_SHARD_COUNT`** consistent on the expander ConfigMap.

**K = 4 template:** **`inspectio-worker-shards-k4.yaml`** defines **`inspectio-worker-shard-0` … `shard-3`**, each overriding **`INSPECTIO_V3_WORKER_SEND_QUEUE_URL`**. Set **`INSPECTIO_V3_SEND_SHARD_COUNT: "4"`** and a **four-element JSON array** for **`INSPECTIO_V3_SEND_QUEUE_URLS`**, then **`kubectl -n inspectio delete deployment inspectio-worker --ignore-not-found`** and apply the shard file (replace **`REPLACE_*`** queue URLs and image). Scale each shard Deployment to split consumer capacity across queues.

## `kubectl apply -k` pitfalls

- **Immutable selectors:** if you change `spec.selector.matchLabels` on an existing Deployment, apply will fail — recreate the workload or avoid changing selectors.
- **StatefulSet** fields such as **`podManagementPolicy`** may not patch in place; treat like immutable.

## Probes

- **L2** (`inspectio-api`) and **L1**: HTTP **`GET /healthz`**.
- **Expander**, **worker**, and **persistence-writer**: no HTTP server — **no probes** in these manifests (acceptable for batch/long-poll workers; add **exec**/**TCP** probes later if desired).

## Exposing L1

**`Service/inspectio-l1`** is **ClusterIP**. Front it with your ingress / NLB / API Gateway; browsers should talk to **L1** only (see P5).

## Load test Jobs (P7)

Driver: **`scripts/v3_load_test.py`** (installed in the image via **`deploy/docker/Dockerfile`**). Uses **`httpx`** against **`INSPECTIO_LOAD_TEST_API_BASE`** (defaults to in-cluster **`http://inspectio-l1:8080`**).

- **Smoke** — **`load-test-job.yaml`**: **`activeDeadlineSeconds: 60`**, **`--sizes "10"`**, waits for ≥10 rows in **`GET /messages/success`** (within API **`limit` ≤ 100**). Wait for completion:

  ```bash
  kubectl apply -f deploy/kubernetes/load-test-job.yaml
  kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-load-test --timeout=65s
  kubectl -n inspectio logs job/inspectio-v3-load-test
  ```

- **Benchmark (admission)** — **`load-test-job-benchmark.yaml`**: **`activeDeadlineSeconds: 600`**, **`--sizes "10000"`**, **`--no-wait-successes`**, **`--max-total-sec 0`** (wall clock bounded by Job only). **`kubectl wait --timeout=620s`** per workspace rules.

- **Sustained repeat (no outcome poll)** — **`load-test-job-sustain.yaml`**: runs **`scripts/v3_sustained_admit.py`** with high **`--batch`** (default **500**) to push **offered msg/s** with fewer HTTP calls. Override **`--concurrency`** / **`--batch`** in the manifest after setting the image tag. Tune expander with **`INSPECTIO_V3_EXPANDER_PUBLISH_CONCURRENCY`** and **`INSPECTIO_V3_EXPANDER_BULK_RECEIVE_MAX`** (ConfigMap) if the bulk→send fan-out lags admission.

### `eks-10k` image tag + in-cluster sustain (admit ≈10k+ msg/s)

Use a **performance-tuned** image (e.g. built from **`feat/v3-eks-throughput-scale`**) tagged for EKS, then point **all** workloads (api, l1, expander, every send-shard worker Deployment) at the same tag:

```bash
TAG=eks-10k   # or your ECR tag
REGISTRY=194768394273.dkr.ecr.us-east-1.amazonaws.com
IMG="${REGISTRY}/inspectio-v3:${TAG}"
NS=inspectio
for d in inspectio-api inspectio-l1 inspectio-expander \
         inspectio-worker-shard-0 inspectio-worker-shard-1 \
         inspectio-worker-shard-2 inspectio-worker-shard-3; do
  c=$(kubectl -n "$NS" get deploy "$d" -o jsonpath='{.spec.template.spec.containers[0].name}')
  kubectl -n "$NS" set image "deployment/$d" "$c=$IMG"
done
# wait for rollouts …
```

**Sustain Job** (admission-only driver; no success polling): set the Job container image to **`$IMG`**, then apply. Example shape that reached **~14k offered admit msg/s** on a K=4 stack (tune to your cluster):

- **Job name:** e.g. **`inspectio-v3-sustain-10k`**
- **Args:** `python scripts/v3_sustained_admit.py --duration-sec 55 --concurrency 180 --batch 500 --body-prefix p10k`
- **Env:** `INSPECTIO_LOAD_TEST_API_BASE=http://inspectio-l1:8080`

```bash
kubectl -n inspectio delete job inspectio-v3-sustain-10k --ignore-not-found
# edit a one-off Job YAML so .spec.template.spec.containers[0].image matches $IMG, then:
kubectl apply -f your-sustain-10k-job.yaml
kubectl -n inspectio wait --for=condition=complete job/inspectio-v3-sustain-10k --timeout=620s
kubectl -n inspectio logs job/inspectio-v3-sustain-10k
```

**End-to-end completion rate (~SQS consumer throughput):** after the run, wait for queues to drain, then sum **CloudWatch** **`AWS/SQS` → `NumberOfMessagesDeleted`** for **each** send queue (`inspectio-v3-send-0` … `send-{K-1}`) over the load window. **Peak combined** ≈ **sum of per-queue `Sum` (60s period) / 60** for the busiest minute. If admit RPS ≫ deletes/s, scale **expander** and **per-shard worker** replicas and/or raise **`INSPECTIO_V3_EXPANDER_PUBLISH_CONCURRENCY`**, then **rollout restart** workloads that read the ConfigMap. For more **SQS long-polls per worker pod**, set **`INSPECTIO_V3_WORKER_RECEIVE_POLLERS`** (default **2**, max **8**) on the ConfigMap and restart **worker** Deployments only.

**Throughput claims (master 3.1 / 3.2):** report **admission RPS** from the driver JSON. **Completed `try_send` / send-side RPS** is not fully observable via **`GET /messages/success`** when **N > 100** (Redis ring cap). For large **N**, use **worker** pod logs (e.g. **`send_ok`** lines) or metrics — see **`plans/v3_phases/P7_LOAD_HARNESS.md`**.

**Recycle** Deployments / roll the stack before benchmark runs (workspace **`restart-containers-before-inspectio-tests`** / EKS rollouts).

Delete prior Jobs before re-run: **`kubectl -n inspectio delete job inspectio-v3-load-test --ignore-not-found`**.

## Optional persist stub (L4/L5 wire)

To enqueue **`MessageTerminalV1`**-shaped JSON to an extra SQS queue after Redis outcomes, add to the ConfigMap:

```yaml
INSPECTIO_V3_PERSIST_QUEUE_URL: "https://sqs.REGION.amazonaws.com/ACCOUNT/persist-queue"
```

Unset or omit to disable.

## P12.2 / P12.8 persistence transport envs

The API/worker emitter path now supports queue-based durability handoff:

- **`INSPECTIO_V3_PERSIST_EMIT_ENABLED`**: enable transport-backed emitter.
- **`INSPECTIO_V3_PERSIST_DURABILITY_MODE`**: `best_effort` (default) or `strict`.
- **`INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URL`**: primary queue URL (required when enabled).
- **`INSPECTIO_V3_PERSIST_TRANSPORT_DLQ_URL`**: optional fallback queue on publish exhaustion.
- **`INSPECTIO_V3_PERSIST_TRANSPORT_SHARD_COUNT`**: shard count for sharded routing mode.
- **`INSPECTIO_V3_PERSIST_TRANSPORT_QUEUE_URLS`**: JSON array/CSV of queue URLs; length must equal shard count.
- **`INSPECTIO_V3_PERSIST_TRANSPORT_DLQ_URLS`**: optional JSON array/CSV of DLQ URLs; empty or same length as shard count.
- **`INSPECTIO_V3_PERSIST_TRANSPORT_MAX_ATTEMPTS`**
- **`INSPECTIO_V3_PERSIST_TRANSPORT_BACKOFF_BASE_MS`**
- **`INSPECTIO_V3_PERSIST_TRANSPORT_BACKOFF_MAX_MS`**
- **`INSPECTIO_V3_PERSIST_TRANSPORT_BACKOFF_JITTER`**
- **`INSPECTIO_V3_PERSIST_TRANSPORT_MAX_INFLIGHT`** (backpressure cap)
- **`INSPECTIO_V3_PERSIST_TRANSPORT_BATCH_MAX_EVENTS`** (1..10)

## P12.3 / P12.8 writer envs

Writer consumes one persistence transport shard queue and writes compressed segments + checkpoint objects to S3:

- **`INSPECTIO_V3_PERSISTENCE_S3_BUCKET`** (required)
- **`INSPECTIO_V3_PERSISTENCE_S3_PREFIX`** (default `state`)
- **`INSPECTIO_V3_WRITER_SHARD_ID`** (required for sharded mode, in range `[0, SHARD_COUNT-1]`)
- **`INSPECTIO_V3_WRITER_RECEIVE_WAIT_SECONDS`**
- **`INSPECTIO_V3_WRITER_RECEIVE_MAX_EVENTS`**
- **`INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY`** (`1..8`, bounded SQS delete parallelism)
- **`INSPECTIO_V3_WRITER_FLUSH_MAX_EVENTS`**
- **`INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS`** (`1..FLUSH_MAX`, interval-trigger occupancy floor)
- **`INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_INTERVAL_MS`** (legacy alias: `INSPECTIO_V3_WRITER_FLUSH_INTERVAL_MS`; k8s template **`1800`** ms — validate vs completion gates; raising frequency can increase S3 PUTs)
- **`INSPECTIO_V3_PERSISTENCE_CHECKPOINT_EVERY_N_FLUSHES`** (`1..20`, `1` keeps checkpoint-per-flush behavior)
- **`INSPECTIO_V3_WRITER_DEDUPE_EVENT_ID_CAP`**
- **`INSPECTIO_V3_WRITER_WRITE_MAX_ATTEMPTS`**
- **`INSPECTIO_V3_WRITER_WRITE_BACKOFF_BASE_MS`**
- **`INSPECTIO_V3_WRITER_WRITE_BACKOFF_MAX_MS`**
- **`INSPECTIO_V3_WRITER_WRITE_BACKOFF_JITTER`**
- **`INSPECTIO_V3_WRITER_IDLE_SLEEP_SEC`**
- **`INSPECTIO_V3_WRITER_OBS_SNAPSHOT_INTERVAL_SEC`** (parse-friendly `writer_snapshot {...}` log cadence)
- **`INSPECTIO_V3_WRITER_QUEUE_AGE_SAMPLE_INTERVAL_SEC`** (SQS queue-age sampling cadence)
- **`INSPECTIO_V3_WRITER_QUEUE_AGE_TIMEOUT_SEC`** (timeout for queue-age sample call)

For **K=4** shard-aligned writer deployments, use **`inspectio-persistence-writer-shards-k4.yaml`** and
delete the singleton writer Deployment before applying it.
For **K=8**, use **`inspectio-persistence-writer-shards-k8.yaml`** similarly.

## P12.4 worker recovery envs

Recovery bootstrap is opt-in on workers and rehydrates in-memory pending state from
persisted segments/checkpoints before receive loops start:

- **`INSPECTIO_V3_WORKER_RECOVERY_ENABLED`** (`true|false`, default `false`)
- **`INSPECTIO_V3_WORKER_RECOVERY_SHARD`** (shard index this worker owns)
- **`INSPECTIO_V3_PERSISTENCE_S3_BUCKET`** (already used by writer; required when recovery enabled)
- **`INSPECTIO_V3_PERSISTENCE_S3_PREFIX`** (default `state`)

## P12.7 throughput gate runbook (persist off vs on)

For assignment throughput gates, run both profiles in-cluster with identical workload shape:

1. **Persistence off baseline**
   - set `INSPECTIO_V3_PERSIST_EMIT_ENABLED=false`
   - deploy/restart workloads
   - run benchmark Job and save JSON logs to `persist-off.json`
2. **Persistence on profile**
   - set `INSPECTIO_V3_PERSIST_EMIT_ENABLED=true` and run writer deployment
   - deploy/restart workloads
   - run same benchmark Job and save JSON logs to `persist-on.json`
3. Collect CloudWatch peak delete throughput across all send queues (msgs/sec),
   writer lag metric sample, and error rates for both runs.
4. Build gate report:

```bash
python scripts/v3_persistence_throughput_report.py \
  --persist-off-json persist-off.json \
  --persist-on-json persist-on.json \
  --persist-off-delete-rps 12000 \
  --persist-on-delete-rps 9800 \
  --persist-off-writer-lag-ms 0 \
  --persist-on-writer-lag-ms 350 \
  --persist-off-flush-latency-ms 0 \
  --persist-on-flush-latency-ms 400 \
  --writer-lag-cap-ms 30000 \
  --flush-latency-cap-ms 5000 \
  --persist-off-error-rate 0.001 \
  --persist-on-error-rate 0.002 \
  --persist-off-window "2026-03-31T13:37:55Z..2026-03-31T13:42:55Z" \
  --persist-on-window "2026-03-31T13:39:20Z..2026-03-31T13:44:20Z" \
  --image-tag "194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-v3:<tag>" \
  --configmap-sha256 "<sha256>" \
  --profile-equivalence "same image/replicas/shards/job shape; persistence toggle only" \
  --stability-off "stable: no crash loops observed" \
  --stability-on "stable: no crash loops observed" \
  --crash-loop-off false \
  --crash-loop-on false \
  --cloudwatch-evidence "AWS/SQS NumberOfMessagesDeleted + persist transport lag query"
```

The script writes `plans/v3_phases/P12_7_THROUGHPUT_REPORT.md` and classifies gates:

- `target_pass`
- `hard_pass_target_miss`
- `hard_fail_completion`
- `hard_fail_stability`
- `hard_fail_admission`
- `invalid_missing_metrics`
