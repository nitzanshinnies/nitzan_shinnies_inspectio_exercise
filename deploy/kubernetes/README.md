# Greenfield Inspectio on EKS (P10)

Kubernetes manifests for **`src/inspectio/`** only. **Do not** apply **`v1_obsolete/project/deploy/kubernetes/`** for this stack.

Blueprint references: **§7** (AWS runtime), **§28.6** (in-cluster load tests).

## Prerequisites (AWS)

1. **EKS** cluster and `kubectl` configured.
2. **S3 bucket** for journals (writer uses `INSPECTIO_S3_BUCKET`).
3. **SQS FIFO** queue; URL as **`INSPECTIO_INGEST_QUEUE_URL`** (HTTPS, `*.fifo`).
4. **IAM** (IRSA): grant the role in **`serviceaccount.yaml`** **S3** read/write on the bucket prefix and **SQS** `ReceiveMessage`, `DeleteMessage`, `SendMessage`, `SendMessageBatch` on the queue.
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
kubectl -n inspectio create secret generic inspectio-aws --from-env-file=/secure/inspect-aws.env
```

For **real AWS**, do **not** set **`AWS_ENDPOINT_URL`** on API/worker pods.

## Deploy workloads (full stack recycle recommended)

```bash
kubectl apply -k deploy/kubernetes/
kubectl -n inspectio rollout status deployment/inspectio-api
kubectl -n inspectio rollout status deployment/inspectio-worker
```

## Measure performance (normative path)

**Throughput / end-to-end numbers for AWS must come from an in-cluster driver** hitting **`http://inspectio-api:8000`**, not from `kubectl port-forward` on a laptop (see repo workspace rules and **§28.6**).

1. Ensure **`INSPECTIO_OUTCOMES_MAX_LIMIT`** in **ConfigMap** is **≥** your test size (default **10000** here) so **`--wait-outcomes`** can observe all terminals.
2. Use the same **`inspectio-app`** image (includes **`scripts/`**).
3. Apply the Job (delete previous Job first if the name collides):

```bash
kubectl -n inspectio delete job inspectio-load-test --ignore-not-found
kubectl apply -f deploy/kubernetes/load-test-job.yaml
kubectl -n inspectio logs -f job/inspectio-load-test
```

The Job prints JSON with **`admission_rps`**, chunk latency percentiles, and (with **`--wait-outcomes`**) **`e2e_rps`** and **`drain_sec`**.

Tune **`--sizes`**, **`--chunk-max`**, and Job resource limits to suit your cluster.

## Public ingress

Expose **`inspectio-api`** with your platform pattern (ALB Ingress, Gateway API, etc.); this directory leaves the Service as **ClusterIP** only.
