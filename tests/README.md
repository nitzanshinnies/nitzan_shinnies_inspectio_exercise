# Tests

## Unit (`tests/unit/`)

TDD against **`tests/reference_spec.py`** and **`plans/REST_API.md`**. Stubs in **`src/`** keep most of **`pytest tests/unit`** red until domain and API are implemented; **`GET /healthz`** liveness smoke may pass.

```bash
pytest tests/unit
pytest -m unit
```

## Integration (`tests/integration/`)

See **`integration/README.md`**. Contract tests + stack liveness; heavy scenarios **skipped** until backends exist.

```bash
pytest tests/integration
pytest -m integration
```

## End-to-end (`tests/e2e/`)

Placeholders for **`plans/TESTS.md` §6**.

```bash
pytest tests/e2e
pytest -m e2e
```
