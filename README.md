# Inspectio exercise

Implementation targets **v3** only. **Normative docs:** **`plans/ASSIGNMENT.pdf`** (local, gitignored), **`plans/openapi.yaml`**, **`plans/V3_ASYNC_PIPELINE_IMPLEMENTATION_PLAN.md`**. **Do not** copy or import legacy code paths — see **`.cursor/rules/inspectio-implementation-no-legacy.mdc`**.

- **`v2_obsolete/plans/`** — archived **v2** specifications and the **V2 EKS throughput post mortem** (historical only; not an implementation spec for v3): blueprint, phased delivery, SQS FIFO throughput plan, performance options, **`V2_THROUGHPUT_POST_MORTEM.md`**.

## Local stack

The **repository root** `docker-compose.yml` is the supported local stack for current services. Compose project name is **`inspectio`** (`name:` in the file). Stop it with:

```bash
docker compose down
```

Bring it up (rebuild when `Dockerfile` / deps change):

```bash
docker compose up -d --build
```

Services: **redis**, **localstack** (S3 + SQS), **mock-sms** (image **`deploy/mock-sms/Dockerfile`**), **inspectio-api**, **inspectio-worker**, **inspectio-notification** (shared **`deploy/docker/Dockerfile`**) — exact set may change as v3 lands; see **`docker-compose.yml`**.

| Service        | Host URL / port |
|----------------|-----------------|
| API            | `http://127.0.0.1:8000` — `GET /healthz` |
| Notification   | `http://127.0.0.1:8081` |
| Mock SMS       | `http://127.0.0.1:8090` |
| LocalStack     | `http://127.0.0.1:4566` |
| Redis          | `127.0.0.1:6379` |

### AWS S3 and credentials

- **Bucket name:** default **`inspectio-test-bucket`**. Override with **`INSPECTIO_S3_BUCKET`** or **`S3_BUCKET`**. Layout for durable state is defined when persistence ships (see **v3 plan** and **ASSIGNMENT.pdf**).
- **Same credentials as the AWS CLI:** Compose injects **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`**, optional **`AWS_SESSION_TOKEN`**, **`AWS_DEFAULT_REGION`**, and **`AWS_ENDPOINT_URL`** into app containers. Defaults **`test` / `test`** and **`http://localstack:4566`** are for LocalStack only.
- Copy **`.env.example`** → **`.env`** and edit, or export variables in your shell before `docker compose up` (e.g. `eval "$(aws configure export-credentials --format env --profile …)"` when your CLI uses SSO or temporary keys). **`.env`** is gitignored.

LocalStack’s init script (**`deploy/localstack/init/ready.d/10-inspectio-aws.sh`**) runs **inside** the LocalStack container and always uses **`aws --endpoint-url=http://localhost:4566`** there; it does not read your laptop’s `~/.aws` unless you extend the image or mount it (not required for normal dev).

Python package: **`pip install -e ".[dev]"`** from repo root (`src/inspectio/`).

### Compose smoke

After a full stack recycle (`docker compose up -d --build --force-recreate`), verify admission → worker → outcomes (exact steps depend on current v3 milestone):

```bash
python3 scripts/compose_smoke.py
```

Uses **`INSPECTIO_SMOKE_API`** (default `http://127.0.0.1:8000`). Exits **0** when the message appears in **`GET /messages/success`**.

### Port conflicts

If another compose stack or local services already bind **6379**, **8000**, **8081**, **8090**, or **4566**, stop them before bringing this stack up.

### AWS (EKS) and in-cluster performance

For **production-shaped** deploy and **throughput** numbers, use **`deploy/kubernetes/`** and the in-cluster **`Job`** in **`deploy/kubernetes/load-test-job.yaml`** (driver: **`scripts/full_flow_load_test.py`**). Do not treat laptop **`kubectl port-forward`** as authoritative AWS performance claims. See **`deploy/kubernetes/README.md`** for IAM, images, secrets, and how to read Job logs.

Local assignment PDF (gitignored): **`plans/ASSIGNMENT.pdf`**.
