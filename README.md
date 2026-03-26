# Inspectio exercise

- **`plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** — normative architecture and **§29** agent contract.
- **`plans/IMPLEMENTATION_PHASES.md`** — phased implementation plan for the greenfield code (separate PR).
- **`plans/openapi.yaml`** — canonical HTTP JSON shapes (**§15** + **§29.6** + mock **`/send`**).
- **`docker-compose.yml`** — **Redis**, **LocalStack** (S3 + Kinesis), **mock-sms** (from `v1_obsolete/project`) only; app containers are added with the implementation PR.

The previous runnable tree is archived under **`v1_obsolete/`**.

Local assignment PDF (gitignored): **`plans/ASSIGNMENT.pdf`**.
