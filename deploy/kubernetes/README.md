# Kubernetes (inspectio exercise)

Kustomize bundle for the same topology as `docker-compose.yml`: Redis, persistence (local directory backend + PVC), notification, mock SMS, **StatefulSet** worker(s), API, health monitor, and nginx web UI.

## Prerequisites

- A cluster with a default `StorageClass` (for `persistence-local-s3` PVC), or adjust the PVC.
- Container images available to the cluster:
  - `inspectio-exercise:latest` — build from repo root (`Dockerfile`).
  - `inspectio-web:latest` — build from `frontend/` (`frontend/Dockerfile`).

**Minikube / kind (images on the node):**

```bash
# minikube
eval $(minikube docker-env)
docker build -t inspectio-exercise:latest .
docker build -t inspectio-web:latest ./frontend

# kind
docker build -t inspectio-exercise:latest .
docker build -t inspectio-web:latest ./frontend
kind load docker-image inspectio-exercise:latest
kind load docker-image inspectio-web:latest
```

**Registry:** change the `images` block in `kustomization.yaml` or use:

```bash
kubectl apply -k deploy/kubernetes/ --dry-run=client -o yaml | sed 's|inspectio-exercise:latest|your.registry/inspectio:v1|g' | kubectl apply -f -
```

## Deploy

```bash
kubectl apply -k deploy/kubernetes
kubectl -n inspectio rollout status deployment/api --timeout=120s
kubectl -n inspectio get pods
```

## Peer HTTP tuning (ConfigMap)

`inspectio-config` includes **`INSPECTIO_HTTPX_MAX_CONNECTIONS`**, **`INSPECTIO_HTTPX_MAX_KEEPALIVE_CONNECTIONS`**, **`INSPECTIO_HTTPX_POOL_TIMEOUT_SEC`**, and **`INSPECTIO_WORKER_MAX_PARALLEL_HANDLES`** (defaults match `inspectio_exercise.common.http_client` and the worker runtime). The **api** Deployment and **worker** StatefulSet read these keys. Edit the ConfigMap and restart workloads to tune pools or per-tick parallelism (e.g. before large load tests or when using AWS S3).

## Access

- **Port-forward UI (same paths as compose):**

  ```bash
  kubectl -n inspectio port-forward svc/web 3000:80
  ```

  Open `http://127.0.0.1:3000` (nginx proxies `/messages` and `/healthz` to `api:8000`).

- **Port-forward API only:**

  ```bash
  kubectl -n inspectio port-forward svc/api 8000:8000
  ```

- **Ingress:** uncomment `ingress.yaml` in `kustomization.yaml` resources, set `ingressClassName` and host to match your controller, then `kubectl apply -k deploy/kubernetes`.

- **Health monitor + persistence** (for `scripts/full_flow_load_test.py`): in another terminal, forward:

  ```bash
  kubectl -n inspectio port-forward svc/health-monitor 8003:8003
  kubectl -n inspectio port-forward svc/persistence 8001:8001
  ```

## Full-flow load test

[`scripts/full_flow_load_test.py`](../scripts/full_flow_load_test.py) exercises `POST /messages/repeat`, waits for pending to drain, runs the health monitor integrity check, and validates lifecycle object counts. For Kubernetes, use **`--kubernetes`** so counts and drain use the persistence API (data stays in the PVC; no host `LOCAL_S3_ROOT`).

With port-forwards for **web** (or **api**), **health-monitor**, and **persistence**:

```bash
pip install -e ".[dev]"
kubectl -n inspectio port-forward svc/web 3000:80 &
kubectl -n inspectio port-forward svc/health-monitor 8003:8003 &
kubectl -n inspectio port-forward svc/persistence 8001:8001 &
python scripts/full_flow_load_test.py --kubernetes \
  --api-base http://127.0.0.1:3000 \
  --health-monitor-base http://127.0.0.1:8003 \
  --persistence-base http://127.0.0.1:8001 \
  --http-timeout-sec 300 \
  --integrity-timeout-sec 900
```

**Smoke** (small batches): add e.g. `--sizes 5,10` so default mock audit limits are not exceeded.

**Large batches** (default `10_000,20_000,30_000`): patch **mock-sms** and **health-monitor** Deployments with the same env as compose (`INSPECTIO_MOCK_FAILURE_RATE=0`, raised `INSPECTIO_MOCK_AUDIT_LOG_MAX_ENTRIES` / `INSPECTIO_MOCK_AUDIT_SENDS_MAX_LIMIT`), then restart those pods.

## Configuration

- **`configmap.yaml`:** `TOTAL_SHARDS`, `SHARDS_PER_POD`, service URLs, `INSPECTIO_WORKER_ACTIVATION_URLS` (default targets `worker-0` on the headless `worker` Service).
- **Scale workers:** increase `StatefulSet` `replicas` and extend `INSPECTIO_WORKER_ACTIVATION_URLS` with comma-separated `http://worker-0.worker:8004,http://worker-1.worker:8004,...`, and set `SHARDS_PER_POD` / `INSPECTIO_WORKER_SHARDS_PER_POD` so `shard_id // shards_per_pod` maps pods correctly (see `README.md` worker env table).

## AWS S3 persistence

Switch persistence Deployment env from ConfigMap `local` keys to a **Secret** (or patched Deployment) with `INSPECTIO_PERSISTENCE_BACKEND=aws`, `INSPECTIO_S3_BUCKET`, and usual `AWS_*` credentials. Remove or do not mount the PVC when using S3.

## Delete

```bash
kubectl delete -k deploy/kubernetes
```

Persistent data: delete PVC explicitly if you want to drop local-s3 state:

```bash
kubectl -n inspectio delete pvc persistence-local-s3
```
