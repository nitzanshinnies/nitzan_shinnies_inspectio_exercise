# Integration tests (`plans/TESTS.md` §5)

**Scope:** this directory only. Assertions target **contracts** from the plans; production code may still be skeleton — then contract tests **fail** (TDD) until an implementation branch lands.

| Module | Role |
|--------|------|
| `test_integration_stack_liveness.py` | All six FastAPI apps respond to **GET /healthz** (wiring smoke). |
| `test_api_activation.py` | Public REST shapes/status codes per **REST_API.md** §3 (red until API implemented). |
| `test_persistence_service.py` | Persistence **HTTP** + local file backend (put/get/list/delete, shard prefix scope, 503 unconfigured). |
| `test_notification_outcomes.py` | **Skipped** placeholders for §4.5 / notification + Redis. |
| `test_health_monitor_reconcile.py` | Mock SMS + persistence + health monitor: **`POST /internal/v1/integrity-check`** vs lifecycle keys (`plans/HEALTH_MONITOR.md`, `plans/TESTS.md` §5.6). |
| `test_worker_bootstrap.py` | **Skipped** placeholders for §5.2 / §5.4. |

```bash
pytest tests/integration -m integration
```

Do **not** change **`src/`** on a tests-only branch unless the team explicitly allows test harness helpers under **`tests/`**.
