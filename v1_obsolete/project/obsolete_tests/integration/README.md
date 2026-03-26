# Integration tests (`plans/TESTS.md` §5)

**Scope:** this directory only. Assertions target **contracts** from the plans; production code may still be skeleton — then contract tests **fail** (TDD) until an implementation branch lands.

| Module | Role |
|--------|------|
| `test_integration_stack_liveness.py` | All six FastAPI apps respond to **GET /healthz** (wiring smoke). |
| `test_api_activation.py` | **REST_API.md** §3 + **TESTS.md** §5.3: contract + durable `state/pending/shard-*/` + worker/mock activation (via shared e2e stack). |
| `test_persistence_service.py` | Persistence **HTTP** + local file backend (put/get/list/delete, shard prefix scope, 503 unconfigured). |
| `test_notification_outcomes.py` | **TESTS.md** §4.5: notification log + hydration cap, API outcomes path spy (no terminal `list_prefix` on GET). |
| `test_health_monitor_reconcile.py` | Mock SMS + persistence + health monitor: **`POST /internal/v1/integrity-check`** vs lifecycle keys (`plans/HEALTH_MONITOR.md`, `plans/TESTS.md` §5.6). |
| `test_worker_bootstrap.py` | **TESTS.md** §5.2 / §5.4: due-queue ordering from pendings, malformed JSON skip, transient `list_prefix` retries. |
| `spy_persistence.py` | Test helper: `SpyPersistenceClient` for persistence call recording. |

```bash
pytest obsolete_tests/integration -m integration
```

Do **not** change **`src/`** on a tests-only branch unless the team explicitly allows test harness helpers under **`obsolete_tests/`**.
