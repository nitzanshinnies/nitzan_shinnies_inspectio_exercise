# Tests

## Unit (`obsolete_tests/unit/`)

TDD against **`obsolete_tests/reference_spec.py`** and **`plans/REST_API.md`**. Stubs in **`src/`** keep most of **`pytest obsolete_tests/unit`** red until domain and API are implemented; **`GET /healthz`** liveness smoke may pass.

```bash
pytest obsolete_tests/unit
pytest -m unit
```

## Integration (`obsolete_tests/integration/`)

See **`integration/README.md`**. Contract tests + stack liveness; heavy scenarios **skipped** until backends exist.

```bash
pytest obsolete_tests/integration
pytest -m integration
```

## End-to-end (`obsolete_tests/e2e/`)

In-process **ASGI** stack (persistence + mock SMS + notification + API + worker) per **`plans/TESTS.md` §6** — requires **`asgi-lifespan`** (dev extra). One **terminal-failure** case remains **skipped** pending scheduler/fake-clock follow-up.

```bash
pytest obsolete_tests/e2e
pytest -m e2e
```
