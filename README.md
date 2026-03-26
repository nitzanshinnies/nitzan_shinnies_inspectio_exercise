# Inspectio exercise

- **`plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** — normative architecture and **§29** agent contract.
- **`plans/IMPLEMENTATION_PHASES.md`** — phased implementation plan (P0–P10).
- **`plans/openapi.yaml`** — canonical HTTP JSON shapes (**§15** + **§29.6** + mock **`/send`**).

## Local stack (v2)

The **repository root** `docker-compose.yml` is the **only** supported local stack for greenfield work. Compose project name is **`inspectio`** (`name:` in the file). Stop it with:

```bash
docker compose down
```

Bring it up (rebuild when `Dockerfile` / deps change):

```bash
docker compose up -d --build
```

Services: **redis**, **localstack** (S3 + Kinesis), **mock-sms** (build context **`v1_obsolete/project`** — code only, not the obsolete compose stack), **inspectio-api**, **inspectio-worker**, **inspectio-notification** (shared **`deploy/docker/Dockerfile`**).

| Service        | Host URL / port |
|----------------|-----------------|
| API            | `http://127.0.0.1:8000` — `GET /healthz` |
| Notification   | `http://127.0.0.1:8081` |
| Mock SMS       | `http://127.0.0.1:8090` |
| LocalStack     | `http://127.0.0.1:4566` |
| Redis          | `127.0.0.1:6379` |

### AWS S3 and credentials (aligned with v1)

- **Bucket name:** default **`inspectio-test-bucket`**, matching v1’s `obsolete_tests/unit/test_aws_s3_provider.py`. Override with **`INSPECTIO_S3_BUCKET`** or v1’s alternate **`S3_BUCKET`** (see `v1_obsolete/project/src/inspectio_exercise/persistence/config.py`).
- **Object key layout** for lifecycle data is still the v1 tree under **`state/`** (`state/pending/…`, `state/success/…`, etc.); that is not the bucket *name* — see v1 **`reference_spec.py`** / **`LOCAL_S3.md`**.
- **Same credentials as the AWS CLI:** Compose injects **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`**, optional **`AWS_SESSION_TOKEN`**, **`AWS_DEFAULT_REGION`**, and **`AWS_ENDPOINT_URL`** into app containers. Defaults **`test` / `test`** and **`http://localstack:4566`** are for LocalStack only.
- Copy **`.env.example`** → **`.env`** and edit, or export variables in your shell before `docker compose up` (e.g. `eval "$(aws configure export-credentials --format env --profile …)"` when your CLI uses SSO or temporary keys). **`.env`** is gitignored.

LocalStack’s init script (**`deploy/localstack/init/ready.d/10-inspectio-aws.sh`**) runs **inside** the LocalStack container and always uses **`aws --endpoint-url=http://localhost:4566`** there; it does not read your laptop’s `~/.aws` unless you extend the image or mount it (not required for normal dev).

Python package: **`pip install -e ".[dev]"`** from repo root (`src/inspectio/` scaffold per **§29.2**).

### Legacy v1 compose

The old multi-service stack under **`v1_obsolete/project/docker-compose.yml`** conflicts on **6379**, **8000**, and other ports with the v2 file above. **Do not run both.** If you still have containers named `nitzan_shinnies_inspectio_exercise-*` from a pre-v2 layout, stop and remove them before `docker compose up` at the repo root.

The previous runnable tree remains archived under **`v1_obsolete/`** for reference only.

Local assignment PDF (gitignored): **`plans/ASSIGNMENT.pdf`**.
