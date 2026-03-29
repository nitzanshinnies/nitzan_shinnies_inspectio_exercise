# Greenfield Inspectio on EKS (P10)

Kubernetes manifests for **`src/inspectio/`** only. **Do not** apply **`v1_obsolete/project/deploy/kubernetes/`** for this stack.

Blueprint references: **§7** (AWS runtime), **§28.6** (in-cluster load tests).

## Prerequisites (AWS)

1. **EKS** cluster and `kubectl` configured.
2. **S3 bucket** for journals (writer uses `INSPECTIO_S3_BUCKET`).
3. **SQS FIFO** queue; URL as **`INSPECTIO_INGEST_QUEUE_URL`** (HTTPS, `*.fifo`).
4. **IAM** (IRSA): grant the role in **`serviceaccount.yaml`** (ServiceAccount **`inspectio-app`**) **S3** read/write on the bucket prefix and **SQS** `ReceiveMessage`, `DeleteMessage`, `SendMessage`, `SendMessageBatch` on the queue.
5. **Redis**: manifests include an in-cluster **redis** Deployment for parity with compose. For production, point **`INSPECTIO_REDIS_URL`** in **`configmap.yaml`** at **ElastiCache** and drop the **redis** resources from `kustomization.yaml` after validation.

## Build and push images

From the repository root (replace registry/tags):

```bash
export REGISTRY=123456789012.dkr.ecr.us-east-1.amazonaws.com
export TAG=$(git rev-parse --short HEAD)

docker build -f deploy/docker/Dockerfile -t ${REGISTRY}/inspectio-app:${TAG} .
docker build -f deploy/mock-sms/Dockerfile -t ${REGISTRY}/inspectio-mock-sms:${TAG} .

aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin ${REGISTRY%%/*}
docker push ${REGISTRY}/inspectio-app:${TAG}
docker push ${REGISTRY}/inspectio-mock-sms:${TAG}
```

Edit **`configmap.yaml`**, **`serviceaccount.yaml`**, and workload YAMLs to use `${REGISTRY}/inspectio-app:${TAG}` and `${REGISTRY}/inspectio-mock-sms:${TAG}` (or use **Kustomize** `images:` / patches).

## Secret (queue + bucket)

Never commit real URLs. Use **`secret-aws.env.example`** as a template:

```bash
cp deploy/kubernetes/secret-aws.env.example /secure/inspect-aws.env
# edit values
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl -n inspectio create secret generic inspectio-secrets --from-env-file=/secure/inspect-aws.env
```

The Secret name **`inspectio-secrets`** matches **`secretRef`** on API and worker pods. **Keys inside** the Secret remain **`INSPECTIO_*`** / **`AWS_*`** (see the example file); only the Kubernetes object name changed from older `inspectio-aws` docs.

For **real AWS**, do **not** set **`AWS_ENDPOINT_URL`** on API/worker pods.

## Deploy workloads (full stack recycle recommended)

```bash
kubectl apply -k deploy/kubernetes/
kubectl -n inspectio rollout status deployment/inspectio-api
kubectl -n inspectio rollout status statefulset/inspectio-worker-sts
```

**Workers:** the stack uses **`StatefulSet` `inspectio-worker-sts`** (not a Deployment). Set **`INSPECTIO_WORKER_REPLICAS`** in **`configmap.yaml`** to the **same value** as **`spec.replicas`** on the StatefulSet so snapshot shard ownership matches. Pods export **`INSPECTIO_WORKER_INDEX`** from the pod ordinal (`HOSTNAME` suffix). **`podManagementPolicy: Parallel`** speeds rollouts (Kubernetes does **not** allow changing this field on an existing StatefulSet; recreate the STS if you need to switch from `OrderedReady`).

## Measure performance (normative path)

**Throughput / end-to-end numbers for AWS must come from an in-cluster driver** hitting **`http://inspectio-api:8000`**, not from `kubectl port-forward` on a laptop (see repo workspace rules and **§28.6**).

1. Ensure **`INSPECTIO_OUTCOMES_MAX_LIMIT`** in **ConfigMap** is **≥** your test size (default **10000** here) so **`--wait-outcomes`** can observe all terminals.
2. Use the same **`inspectio-app`** image (includes **`scripts/`**).
3. Apply the Job (delete previous Job first if the name collides):

```bash
kubectl -n inspectio delete job inspectio-load-test --ignore-not-found
kubectl apply -f deploy/kubernetes/load-test-job.yaml
kubectl wait --for=condition=complete job/inspectio-load-test -n inspectio --timeout=60s
kubectl -n inspectio logs job/inspectio-load-test
```

The Job is capped at **60s** wall clock (**`activeDeadlineSeconds`**, **`--max-total-sec`**, and **`kubectl wait --timeout=60s`**). It prints JSON with **`admission_rps`**, chunk latency percentiles, and (with **`--wait-outcomes`**) **`e2e_rps`** and **`drain_sec`**.

Tune **`--sizes`**, **`--chunk-max`**, and Job resource limits to suit your cluster.

**Long / N1 admit benchmarks (avoid false timeouts):** keep three limits in sync: (1) **`kubectl wait --timeout`** ≥ expected runtime, (2) Job **`activeDeadlineSeconds`** ≥ that, (3) driver **`--max-total-sec`** either **large enough** or **`0`** (disables the script’s own wall clock so admission can run until Kubernetes stops the pod). See **`deploy/kubernetes/n1-admit-bench-job.yaml`**. Do not start the next Job until the previous one finishes, or **`kubectl wait`** will fire early while work is still running.

## Performance (durability-preserving levers)

Rough order of impact for **in-cluster drain** and **admission** throughput:

1. **Horizontal scale** — Raise **`StatefulSet`** `spec.replicas` and set **`INSPECTIO_WORKER_REPLICAS`** to the same value. Scale **`inspectio-api`** (admission + parallel FIFO sends across groups). Scale **`inspectio-notification`** if terminal HTTP becomes hot.
2. **API admission** — **`INSPECTIO_MAX_SQS_FIFO_INFLIGHT_GROUPS`** (default **64**): higher allows more concurrent `SendMessageBatch` pipelines across distinct `MessageGroupId`s for large **`/messages/repeat`** payloads (see **`plans/SQS_FIFO_THROUGHPUT_AND_ADMISSION_PLAN.md`**).
3. **Worker receive** — **`INSPECTIO_SQS_RECEIVE_CONCURRENCY`** (default **4**): multiple independent long-poll loops per worker pod (each opens its own SQS client) to raise dequeue + §18.3 throughput toward aggregate N1 targets.
4. **Journal batching** — In **`configmap.yaml`**, **`INSPECTIO_JOURNAL_FLUSH_INTERVAL_MS`** and **`INSPECTIO_JOURNAL_FLUSH_MAX_LINES`**: larger windows mean **fewer S3 `PutObject`** calls per shard (slightly higher memory and crash window; still durable once flushed).
5. **Per-shard send parallelism** — **`INSPECTIO_MAX_PARALLEL_SENDS_PER_SHARD`** (worker): raise if mock SMS and CPU allow.
6. **Ingest journal** — **`append_ingest_template_a`** appends only; the worker **flushes each touched shard once per SQS receive batch** before **`DeleteMessage`**, so multiple ingests on the same shard share a segment when possible (§18.3).
7. **Infra** — S3 prefix scaling, optional **high-throughput FIFO**, **ElastiCache** for Redis, right-sized **CPU/memory** on worker pods, **`podManagementPolicy: Parallel`** on **new** StatefulSets for faster rollouts.

**SQS admission:** `SqsFifoIngestProducer` retries **`send_message_batch`** / **`send_message`** with exponential backoff on **throttling** and similar transient `ClientError` codes (see `sqs_fifo_producer.py`).

**Larger architectural options** (FIFO swaps, fewer journal lines, etc.): **`plans/PERFORMANCE_ARCH_FUTURE.md`**.

## Public ingress

Expose **`inspectio-api`** with your platform pattern (ALB Ingress, Gateway API, etc.); this directory leaves the Service as **ClusterIP** only.
