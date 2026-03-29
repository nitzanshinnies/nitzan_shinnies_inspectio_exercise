# Inspectio v3 — Kubernetes (EKS)

Manifests for **namespace `inspectio`**: Redis (dev/in-cluster), **L2** (`inspectio-api`, ≥2 replicas), **expander**, **send worker(s)**, **L1** edge (same container image as L2, different command). **LocalStack is not used here** — point `INSPECTIO_V3_*_QUEUE_URL` values at **real AWS SQS** standard queues.

See **`plans/v3_phases/P6_KUBERNETES.md`**, workspace rule **`inspectio-eks-agent-executes-deploy`**, and **`plans/V3_ASYNC_PIPELINE_IMPLEMENTATION_PLAN.md`**.

## Prerequisites

- Image built from **`deploy/docker/Dockerfile`** and pushed to your registry (e.g. ECR).
- SQS queues: one **bulk** queue and **`K`** **send** queues (`INSPECTIO_V3_SEND_SHARD_COUNT` must match **`INSPECTIO_V3_SEND_QUEUE_URLS`**).
- **IRSA** (recommended): set `eks.amazonaws.com/role-arn` on **`ServiceAccount/inspectio-app`** to a role that can `sqs:ReceiveMessage`, `SendMessage`, `DeleteMessage`, `GetQueueUrl` (and send to optional persist queue if enabled).
- **Redis**: in-cluster Deployment here is for exercise/smoke; production often uses **ElastiCache** — set **`REDIS_URL`** / **`INSPECTIO_REDIS_URL`** in a ConfigMap or Secret to that endpoint.

## Apply order

1. Edit **`configmap.yaml`**: replace `REPLACE_WITH_SQS_*` placeholders; align **`INSPECTIO_V3_SEND_SHARD_COUNT`** with the number of comma-separated send URLs.
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
kubectl -n inspectio rollout status deployment/inspectio-api --timeout=120s
kubectl -n inspectio rollout status deployment/inspectio-l1 --timeout=120s
```

**ConfigMap-only changes** (queue URLs, `K`, Redis URL): `kubectl apply -f deploy/kubernetes/configmap.yaml` then **restart** pods that read it (rollout restart Deployments).

## Multi-shard workers (`K` > 1)

Duplicate **`inspectio-worker.yaml`** per shard (e.g. `inspectio-worker-1.yaml`) with a **unique** `metadata.name` and **`INSPECTIO_V3_WORKER_SEND_QUEUE_URL`** for that shard’s queue. Keep **`INSPECTIO_V3_SEND_QUEUE_URLS`** and **`INSPECTIO_V3_SEND_SHARD_COUNT`** consistent on the expander ConfigMap.

## `kubectl apply -k` pitfalls

- **Immutable selectors:** if you change `spec.selector.matchLabels` on an existing Deployment, apply will fail — recreate the workload or avoid changing selectors.
- **StatefulSet** fields such as **`podManagementPolicy`** may not patch in place; treat like immutable.

## Probes

- **L2** (`inspectio-api`) and **L1**: HTTP **`GET /healthz`**.
- **Expander** and **worker**: no HTTP server — **no probes** in these manifests (acceptable for batch/long-poll workers; add **exec**/**TCP** probes later if desired).

## Exposing L1

**`Service/inspectio-l1`** is **ClusterIP**. Front it with your ingress / NLB / API Gateway; browsers should talk to **L1** only (see P5).

## Optional persist stub (L4/L5 wire)

To enqueue **`MessageTerminalV1`**-shaped JSON to an extra SQS queue after Redis outcomes, add to the ConfigMap:

```yaml
INSPECTIO_V3_PERSIST_QUEUE_URL: "https://sqs.REGION.amazonaws.com/ACCOUNT/persist-queue"
```

Unset or omit to disable.
