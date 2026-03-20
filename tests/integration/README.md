# Integration tests (`plans/TESTS.md` §5)

**Scope:** this directory only. Assertions target **contracts** from the plans; production code may still be skeleton — then contract tests **fail** (TDD) until an implementation branch lands.

| Module | Role |
|--------|------|
| `test_integration_stack_liveness.py` | All six FastAPI apps respond to **GET /healthz** (wiring smoke). |
| `test_api_activation.py` | Public REST shapes/status codes per **REST_API.md** §3 (red until API implemented). |
| `test_persistence_service.py` | **Skipped** placeholders for §5.1 (moto, owned prefixes). |
| `test_notification_outcomes.py` | **Skipped** placeholders for §4.5 / notification + Redis. |
| `test_health_monitor_reconcile.py` | **Skipped** placeholder for §5.6 integrity POST. |
| `test_worker_bootstrap.py` | **Skipped** placeholders for §5.2 / §5.4. |

```bash
pytest tests/integration -m integration
```

Do **not** change **`src/`** on a tests-only branch unless the team explicitly allows test harness helpers under **`tests/`**.
