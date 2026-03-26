# Inspectio exercise

- **`plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** — normative architecture and **§29** agent contract.
- **`plans/IMPLEMENTATION_PHASES.md`** — phased implementation plan (P0–P10).
- **`plans/openapi.yaml`** — canonical HTTP JSON shapes (**§15** + **§29.6** + mock **`/send`**).
- **Greenfield code** lives in **`src/inspectio/`** only — **do not** import or copy from **`v1_obsolete/`** (archived); see **`IMPLEMENTATION_PHASES.md`** (*`v1_obsolete` boundary*) and blueprint **§29.11**.

## Local stack (v2)

The **repository root** `docker-compose.yml` is the **only** supported local stack for greenfield work. Compose project name is **`inspectio`** (`name:` in the file). Stop it with:

```bash
docker compose down
```

Bring it up (rebuild when `Dockerfile` / deps change):

```bash
docker compose up -d --build
```

Services: **redis**, **localstack** (S3 + Kinesis), **mock-sms** (image **`deploy/mock-sms/Dockerfile`**), **inspectio-api**, **inspectio-worker**, **inspectio-notification** (shared **`deploy/docker/Dockerfile`**).

| Service        | Host URL / port |
|----------------|-----------------|
| API            | `http://127.0.0.1:8000` — `GET /healthz` |
| Notification   | `http://127.0.0.1:8081` |
| Mock SMS       | `http://127.0.0.1:8090` |
| LocalStack     | `http://127.0.0.1:4566` |
| Redis          | `127.0.0.1:6379` |

### P9 smoke flow

After `docker compose up -d --build`, run:

```bash
python scripts/p9_compose_smoke.py
```

This performs the Phase-9 smoke path:
- `POST /messages`
- poll `GET /messages/success|failed`
- assert the submitted `messageId` appears in terminal projection

Optional pytest wrapper (disabled unless explicitly enabled):

```bash
RUN_P9_E2E_SMOKE=1 pytest -m e2e -q
```

## Phase-10 AWS/EKS runbook

Phase 10 validation is **in-cluster only** for AWS claims. Do not use laptop
`port-forward` as a baseline.

### 1) Prepare manifests

- Edit placeholders in:
  - `deploy/kubernetes/serviceaccount.yaml` (`eks.amazonaws.com/role-arn`)
  - `deploy/kubernetes/api.yaml`, `worker.yaml`, `notification.yaml`, `load-test-in-cluster-job.yaml` (`image`)
- Create runtime secret from `deploy/kubernetes/secrets.example.yaml`:
  - set `INSPECTIO_S3_BUCKET`
  - set `INSPECTIO_REDIS_URL`
  - set in-cluster `INSPECTIO_NOTIFICATION_BASE_URL` and `INSPECTIO_SMS_URL`

### 2) Deploy app services

```bash
kubectl apply -f deploy/kubernetes/secrets.example.yaml
kubectl apply -k deploy/kubernetes
```

### 3) Restart workloads before load tests

Default policy for integration/load runs is a full recycle of participating
workloads in the `inspectio` namespace.

```bash
kubectl -n inspectio rollout restart deployment --all
kubectl -n inspectio rollout restart statefulset --all
kubectl -n inspectio rollout status deployment/inspectio-api
kubectl -n inspectio rollout status deployment/inspectio-worker
kubectl -n inspectio rollout status deployment/inspectio-notification
```

### 4) Run load test inside the cluster

```bash
kubectl -n inspectio delete job inspectio-full-flow-load-test --ignore-not-found
kubectl -n inspectio apply -f deploy/kubernetes/load-test-in-cluster-job.yaml
kubectl -n inspectio logs -f job/inspectio-full-flow-load-test
```

The job runs:

```bash
python scripts/full_flow_load_test.py --kubernetes --api-base-url http://inspectio-api.inspectio.svc.cluster.local:8000
```

For larger loads, raise query depth so the reader can observe recent terminal rows:

```bash
python scripts/full_flow_load_test.py --kubernetes --api-base-url http://inspectio-api.inspectio.svc.cluster.local:8000 --count 2000 --limit 1000
```

Exit code `0` means the flow reached terminal outcomes in-cluster.

### AWS S3 and credentials

- **Bucket name:** default **`inspectio-test-bucket`**. Override with **`INSPECTIO_S3_BUCKET`** or **`S3_BUCKET`**. Object layout and semantics are defined in **`plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** — **`v1_obsolete/`** is **not** an implementation source (**see** **`IMPLEMENTATION_PHASES.md`**, *`v1_obsolete` boundary*).
- **Same credentials as the AWS CLI:** Compose injects **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`**, optional **`AWS_SESSION_TOKEN`**, **`AWS_DEFAULT_REGION`**, and **`AWS_ENDPOINT_URL`** into app containers. Defaults **`test` / `test`** and **`http://localstack:4566`** are for LocalStack only.
- Copy **`.env.example`** → **`.env`** and edit, or export variables in your shell before `docker compose up` (e.g. `eval "$(aws configure export-credentials --format env --profile …)"` when your CLI uses SSO or temporary keys). **`.env`** is gitignored.

LocalStack’s init script (**`deploy/localstack/init/ready.d/10-inspectio-aws.sh`**) runs **inside** the LocalStack container and always uses **`aws --endpoint-url=http://localhost:4566`** there; it does not read your laptop’s `~/.aws` unless you extend the image or mount it (not required for normal dev).

Python package: **`pip install -e ".[dev]"`** from repo root (`src/inspectio/` scaffold per **§29.2**).

### Port conflicts

If another compose stack or local services already bind **6379**, **8000**, **8081**, **8090**, or **4566**, stop them before bringing this stack up.

Local assignment PDF (gitignored): **`plans/ASSIGNMENT.pdf`**.
