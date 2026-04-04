# Archived v2 implementation

This tree is a **frozen snapshot** of the pre–v3 codebase: application package, tests, scripts, Docker app image, mock-SMS service, and Kubernetes manifests. **Do not** import or copy from here into **`src/inspectio/`** or **`tests/`** when building v3 (see **`.cursor/rules/inspectio-implementation-no-legacy.mdc`**).

| Path | Contents |
|------|----------|
| `src/inspectio/` | v2 Python package (API, worker, ingest, notification, domain) |
| `tests/` | v2 unit, integration, e2e tests |
| `scripts/` | `full_flow_load_test.py`, `compose_smoke.py` |
| `deploy/docker/` | v2 multi-service Dockerfile (copied `scripts/` into image) |
| `deploy/mock-sms/` | mock SMS HTTP stub image |
| `deploy/kubernetes/` | Deployments, Jobs, ConfigMaps, etc. |

Normative behavior for v3 remains **`plans/ASSIGNMENT.pdf`**, **`plans/openapi.yaml`**, and **`plans/V3_ASYNC_PIPELINE_IMPLEMENTATION_PLAN.md`**.
