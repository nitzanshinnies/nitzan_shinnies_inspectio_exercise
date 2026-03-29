# V3 phase plans

Expansion of **`plans/V3_ASYNC_PIPELINE_IMPLEMENTATION_PLAN.md`** into merge-sized work units. **Normative order** matches the master plan phase table (**P0 → P7**).

**Before coding:** master plan → **`plans/openapi.yaml`** (OpenAPI-first) → **`.cursor/rules/`** in the repo + workspace (testing, performance, no legacy imports). **No Kinesis.** **No** code from **`v2_obsolete/archive/`**.

## Phase map

| Phase | Doc | Master plan |
|-------|-----|-------------|
| P0 | [P0_PACKAGE_AND_SURFACE.md](./P0_PACKAGE_AND_SURFACE.md) | Package **`inspectio.v3`**, Pydantic envelopes, **`assignment_surface`**, retry pure functions |
| P1 | [P1_L2_HTTP_AND_STUB_ENQUEUE.md](./P1_L2_HTTP_AND_STUB_ENQUEUE.md) | L2 routes, OpenAPI sync, stub **`BulkIntentV1`** enqueue |
| P2 | [P2_SQS_AND_LOCALSTACK.md](./P2_SQS_AND_LOCALSTACK.md) | **SQS** (**aioboto3**), LocalStack, backoff |
| P3 | [P3_EXPANDER.md](./P3_EXPANDER.md) | Bulk → **N × SendUnitV1**, sharded send queues |
| P4 | [P4_SEND_WORKER_AND_OUTCOMES.md](./P4_SEND_WORKER_AND_OUTCOMES.md) | L4 scheduler, **`wakeup`**, **`try_send`**, Redis outcomes, e2e compose |
| P5 | [P5_L1_STATIC_AND_PROXY.md](./P5_L1_STATIC_AND_PROXY.md) | L1 static + proxy (browser → L1 only) |
| P6 | [P6_KUBERNETES.md](./P6_KUBERNETES.md) | **`deploy/kubernetes/`**, ConfigMap/Secrets, multi-replica L2 |
| P7 | [P7_LOAD_HARNESS.md](./P7_LOAD_HARNESS.md) | In-cluster Job + driver; primary metric (master plan **3.1**); bounded waits |

## Dependencies

**Same order as master plan phase table:**

```text
P0 → P1 → P2 → P3 → P4 → P5 → P6 → P7
```

**Exception:** **P7** driver may target L2 **Service** only, so a minimal **P6** (no L1 image) is valid if **P4** is done; **P5** can follow in a later PR. **Full** **7.2** checklist (L1 proxy for browsers) needs **P5** before treating the product as complete.

**P7** needs deployable workloads (**P6** or equivalent) and the **3.1** **`try_send`** path (**P4**).

## Conventions

Python **3.11+**, type hints, **four-group imports**, atomic functions. Tests use markers **`unit`**, **`integration`**, **`e2e`**, **`performance`** per **`pyproject.toml`**. **AWS throughput claims:** in-cluster Job only (see **P7**, workspace rules).

**Traceability matrix:** [VALIDATION_CHECKLIST.md](./VALIDATION_CHECKLIST.md) (master plan rows ↔ phases, tick when implemented).
