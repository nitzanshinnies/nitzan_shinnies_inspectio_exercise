# Inspectio exercise

- **`plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** — normative architecture and **§29** agent contract.
- **`plans/IMPLEMENTATION_PHASES.md`** — phased implementation plan (P0–P10).
- **`plans/openapi.yaml`** — canonical HTTP JSON shapes (**§15** + **§29.6** + mock **`/send`**).

## Local stack

```bash
docker compose up -d --build
```

Services: **redis**, **localstack** (S3 + Kinesis), **mock-sms** (image from `v1_obsolete/project`), **inspectio-api**, **inspectio-worker**, **inspectio-notification** (shared **`deploy/docker/Dockerfile`**).

- API: `http://127.0.0.1:8000` (`GET /healthz`)
- Notification: `http://127.0.0.1:8081`
- Mock SMS: `http://127.0.0.1:8090`
- LocalStack: `http://127.0.0.1:4566`

Python package: **`pip install -e ".[dev]"`** from repo root (`src/inspectio/` scaffold per **§29.2**).

The previous runnable tree is archived under **`v1_obsolete/`**.

Local assignment PDF (gitignored): **`plans/ASSIGNMENT.pdf`**.
