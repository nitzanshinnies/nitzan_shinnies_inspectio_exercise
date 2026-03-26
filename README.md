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

Python package: **`pip install -e ".[dev]"`** from repo root (`src/inspectio/` scaffold per **§29.2**).

### Legacy v1 compose

The old multi-service stack under **`v1_obsolete/project/docker-compose.yml`** conflicts on **6379**, **8000**, and other ports with the v2 file above. **Do not run both.** If you still have containers named `nitzan_shinnies_inspectio_exercise-*` from a pre-v2 layout, stop and remove them before `docker compose up` at the repo root.

The previous runnable tree remains archived under **`v1_obsolete/`** for reference only.

Local assignment PDF (gitignored): **`plans/ASSIGNMENT.pdf`**.
