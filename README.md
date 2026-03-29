# Inspectio exercise

- **`plans/V2_THROUGHPUT_POST_MORTEM.md`** — throughput and EKS load-testing post mortem for the **v2** stack (measurement narrative and pitfalls).
- **`plans/openapi.yaml`** — canonical HTTP JSON shapes (**§15** + **§29.6** + mock **`/send`**); keep in sync with code until a **v3** spec replaces this contract.
- **`v2_obsolete/plans/`** — archived **v2** normative documents: **`NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** (**§29** agent contract), **`IMPLEMENTATION_PHASES.md`**, **`SQS_FIFO_THROUGHPUT_AND_ADMISSION_PLAN.md`**, **`PERFORMANCE_ARCH_FUTURE.md`**. **V3** design work supersedes that stack; these files remain for traceability.
- **Greenfield code** lives in **`src/inspectio/`** only — **do not** import or copy from **`v1_obsolete/`** (archived); the *`v1_obsolete` boundary* in **`v2_obsolete/plans/IMPLEMENTATION_PHASES.md`** still describes what not to mirror from **`v1_obsolete/`** tests, and blueprint **§29.11** in the same archive applies to the **v2** line.

## Local stack (v2)

The **repository root** `docker-compose.yml` is the **only** supported local stack for greenfield work. Compose project name is **`inspectio`** (`name:` in the file). Stop it with:

```bash
docker compose down
```

Bring it up (rebuild when `Dockerfile` / deps change):

```bash
docker compose up -d --build
```

Services: **redis**, **localstack** (S3 + **SQS FIFO**), **mock-sms** (image **`deploy/mock-sms/Dockerfile`**), **inspectio-api**, **inspectio-worker**, **inspectio-notification** (shared **`deploy/docker/Dockerfile`**).

| Service        | Host URL / port |
|----------------|-----------------|
| API            | `http://127.0.0.1:8000` — `GET /healthz` |
| Notification   | `http://127.0.0.1:8081` |
| Mock SMS       | `http://127.0.0.1:8090` |
| LocalStack     | `http://127.0.0.1:4566` |
| Redis          | `127.0.0.1:6379` |

### AWS S3 and credentials

- **Bucket name:** default **`inspectio-test-bucket`**. Override with **`INSPECTIO_S3_BUCKET`** or **`S3_BUCKET`**. Object layout and semantics for the **v2** line are defined in **`v2_obsolete/plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** — **`v1_obsolete/`** is **not** an implementation source (**see** **`v2_obsolete/plans/IMPLEMENTATION_PHASES.md`**, *`v1_obsolete` boundary*).
- **Same credentials as the AWS CLI:** Compose injects **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`**, optional **`AWS_SESSION_TOKEN`**, **`AWS_DEFAULT_REGION`**, and **`AWS_ENDPOINT_URL`** into app containers. Defaults **`test` / `test`** and **`http://localstack:4566`** are for LocalStack only.
- Copy **`.env.example`** → **`.env`** and edit, or export variables in your shell before `docker compose up` (e.g. `eval "$(aws configure export-credentials --format env --profile …)"` when your CLI uses SSO or temporary keys). **`.env`** is gitignored.

LocalStack’s init script (**`deploy/localstack/init/ready.d/10-inspectio-aws.sh`**) runs **inside** the LocalStack container and always uses **`aws --endpoint-url=http://localhost:4566`** there; it does not read your laptop’s `~/.aws` unless you extend the image or mount it (not required for normal dev).

Python package: **`pip install -e ".[dev]"`** from repo root (`src/inspectio/` scaffold per archived blueprint **§29.2** in **`v2_obsolete/plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`**).

### Compose smoke (P9)

After a full stack recycle (`docker compose up -d --build --force-recreate`), verify admission → worker → SMS → outcomes:

```bash
python3 scripts/compose_smoke.py
```

Uses **`INSPECTIO_SMOKE_API`** (default `http://127.0.0.1:8000`). Exits **0** when the message appears in **`GET /messages/success`**.

### Port conflicts

If another compose stack or local services already bind **6379**, **8000**, **8081**, **8090**, or **4566**, stop them before bringing this stack up.

### AWS (EKS) and in-cluster performance (P10)

For **production-shaped** deploy and **throughput / E2E RPS** numbers, use **`deploy/kubernetes/`** and the in-cluster **`Job`** in **`deploy/kubernetes/load-test-job.yaml`** (driver: **`scripts/full_flow_load_test.py`**). **§28.6:** do not treat laptop **`port-forward`** results as authoritative AWS performance claims. See **`deploy/kubernetes/README.md`** for IAM, images, secrets, and how to read Job logs.

Local assignment PDF (gitignored): **`plans/ASSIGNMENT.pdf`**.
