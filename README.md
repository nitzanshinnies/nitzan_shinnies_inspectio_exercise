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

Services: **redis**, **localstack** (S3 + **SQS FIFO**), **mock-sms** (image **`deploy/mock-sms/Dockerfile`**), **inspectio-api**, **inspectio-worker**, **inspectio-notification** (shared **`deploy/docker/Dockerfile`**).

| Service        | Host URL / port |
|----------------|-----------------|
| API            | `http://127.0.0.1:8000` — `GET /healthz` |
| Notification   | `http://127.0.0.1:8081` |
| Mock SMS       | `http://127.0.0.1:8090` |
| LocalStack     | `http://127.0.0.1:4566` |
| Redis          | `127.0.0.1:6379` |

### AWS S3 and credentials

- **Bucket name:** default **`inspectio-test-bucket`**. Override with **`INSPECTIO_S3_BUCKET`** or **`S3_BUCKET`**. Object layout and semantics are defined in **`plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** — **`v1_obsolete/`** is **not** an implementation source (**see** **`IMPLEMENTATION_PHASES.md`**, *`v1_obsolete` boundary*).
- **Same credentials as the AWS CLI:** Compose injects **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`**, optional **`AWS_SESSION_TOKEN`**, **`AWS_DEFAULT_REGION`**, and **`AWS_ENDPOINT_URL`** into app containers. Defaults **`test` / `test`** and **`http://localstack:4566`** are for LocalStack only.
- Copy **`.env.example`** → **`.env`** and edit, or export variables in your shell before `docker compose up` (e.g. `eval "$(aws configure export-credentials --format env --profile …)"` when your CLI uses SSO or temporary keys). **`.env`** is gitignored.

LocalStack’s init script (**`deploy/localstack/init/ready.d/10-inspectio-aws.sh`**) runs **inside** the LocalStack container and always uses **`aws --endpoint-url=http://localhost:4566`** there; it does not read your laptop’s `~/.aws` unless you extend the image or mount it (not required for normal dev).

Python package: **`pip install -e ".[dev]"`** from repo root (`src/inspectio/` scaffold per **§29.2**).

### Port conflicts

If another compose stack or local services already bind **6379**, **8000**, **8081**, **8090**, or **4566**, stop them before bringing this stack up.

Local assignment PDF (gitignored): **`plans/ASSIGNMENT.pdf`**.
