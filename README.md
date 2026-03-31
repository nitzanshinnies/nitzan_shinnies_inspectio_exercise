# Inspectio exercise

Implementation targets **v3** only. **Normative docs:** **`plans/ASSIGNMENT.pdf`** (local, gitignored), **`plans/openapi.yaml`**, **`plans/V3_ASYNC_PIPELINE_IMPLEMENTATION_PLAN.md`**. **Do not** copy or import legacy code paths — see **`.cursor/rules/inspectio-implementation-no-legacy.mdc`**.

- **`v2_obsolete/plans/`** — archived **v2** specifications and the **V2 EKS throughput post mortem** (historical only).
- **`v2_obsolete/archive/`** — frozen **v2 implementation**: `src/inspectio`, `tests`, `scripts`, `deploy/docker`, `deploy/mock-sms`, `deploy/kubernetes` (see **`v2_obsolete/archive/README.md`**).

## V3 package (phase P0)

- **`inspectio.v3`** lives under **`src/inspectio/v3/`**: queue envelopes **`BulkIntentV1`** / **`SendUnitV1`** (Pydantic, JSON aliases `schemaVersion`, `traceId`, `batchCorrelationId`, `receivedAtMs`, `attemptsCompleted` = **0** before the first `try_send`), pure **`domain/retry_schedule`** (deadlines at **0, 500, 2000, 4000, 8000, 16000** ms after `receivedAtMs`), and **`assignment_surface`** (`Message`, **`try_send` → `bool`**, void **`send`** wrapper). Verify with **`pytest -m unit`**.

## V3 L2 (phase P1)

- **`inspectio.v3.l2`**: FastAPI app from **`create_l2_app`** or **`create_l2_app_from_env()`** (**`inspectio.v3.l2.serve:app`**) — **`POST /messages`** and **`POST /messages/repeat?count=`** each enqueue **one** **`BulkIntentV1`** (single path uses **`count=1`**). **`Idempotency-Key`** with in-process TTL (no second enqueue on replay; **409** if the key is reused with a different payload). Repeat responses use the **summary** shape in **`plans/openapi.yaml`** (`batchCorrelationId`, `count`, `accepted`). **`GET /messages/success|failed`** read **`OutcomesReadPort`** (Redis when **`REDIS_URL`** / **`INSPECTIO_REDIS_URL`** is set in compose; otherwise empty **`items`**). Inject **`clock_ms`** and a **`ListBulkEnqueue`** or **`SqsBulkEnqueue`**; **`BulkEnqueuePort.enqueue`** is **async** (P2 **`aioboto3`**).

## V3 SQS (phase P2)

- **Standard bulk queue** (not FIFO) for **`BulkIntentV1`**: LocalStack init creates **`inspectio-v3-bulk`** (override with **`INSPECTIO_V3_BULK_QUEUE_NAME`**) and **`inspectio-v3-send-0` … `send-(K-1)`** for **`K` = `INSPECTIO_V3_SEND_SHARD_COUNT`** (default **1** in compose).
- **Environment:** **`INSPECTIO_V3_BULK_QUEUE_URL`** (required for real enqueue), **`AWS_ENDPOINT_URL`** (e.g. `http://127.0.0.1:4566` against compose LocalStack), **`AWS_DEFAULT_REGION`**, **`AWS_ACCESS_KEY_ID`** / **`AWS_SECRET_ACCESS_KEY`** (defaults **`test`/`test`** for LocalStack). Use **`build_sqs_bulk_enqueue_from_env()`** from **`inspectio.v3.settings`** or construct **`SqsBulkEnqueue`** manually.
- **Integration test (opt-in):** with LocalStack healthy, set **`INSPECTIO_SQS_INTEGRATION=1`** and **`INSPECTIO_V3_BULK_QUEUE_URL`** to your queue URL (example: `http://127.0.0.1:4566/000000000000/inspectio-v3-bulk`), then run **`pytest tests/integration/test_v3_sqs_bulk_roundtrip.py -m integration`**. CI without Docker leaves these unset so the test is skipped.

## V3 expander (phase P3)

- **`inspectio.v3.expander`**: long-poll **`INSPECTIO_V3_BULK_QUEUE_URL`**, parse **`BulkIntentV1`**, emit **N × `SendUnitV1`** with **`stable_hash(messageId) % K`** routing to **`INSPECTIO_V3_SEND_QUEUE_URLS`** (comma-separated, length must equal **`INSPECTIO_V3_SEND_SHARD_COUNT`**). **`SendMessageBatch`** (chunks of 10) per shard; throttle-style batch failures retry with the same backoff helper as P2. **`DeleteMessage`** on the bulk receipt only after all publishes succeed; if publish fails, the bulk message becomes visible again after **`INSPECTIO_V3_BULK_VISIBILITY_TIMEOUT`** (visibility timeout on receive).
- **Dedupe (single replica):** in-memory LRU of bulk **SQS `MessageId`** after successful publish; redelivery after publish skips fan-out and only deletes (multi-replica dedupe would use **Redis `SETNX`** — not implemented here).
- **Run:** **`inspectio-v3-expander`** (console script) or **`python -m inspectio.v3.expander`** with env set.
- **Integration (opt-in):** **`INSPECTIO_EXPANDER_INTEGRATION=1`**, LocalStack queues created, then **`pytest tests/integration/test_v3_expander_roundtrip.py -m integration`**.

## V3 send worker + outcomes (phase P4)

- **`inspectio.v3.worker`**: long-poll **`ReceiveMessage`** on **one** send shard queue (**`INSPECTIO_V3_WORKER_SEND_QUEUE_URL`**), plus a **`~500 ms`** **`asyncio.sleep`** wakeup that scans due **`try_send`** attempts. **One OS process per send queue** (or run multiple processes with different URLs for **`K > 1`**). **`try_send`** defaults to always **`True`** (**`INSPECTIO_V3_TRY_SEND_ALWAYS_SUCCEED`**, default **`true`**); set to **`false`** to force retry/backoff and eventual **failed** terminal after six failures.
- **Per-`messageId`:** **`asyncio.Lock`** + in-memory active/terminal dedupe so duplicate SQS deliveries do not double-apply side effects; extra receipts are **deleted** after dedupe.
- **Optional L5 stub:** when **`INSPECTIO_V3_PERSIST_QUEUE_URL`** is set, the worker **`SendMessage`**s a small **`MessageTerminalV1`**-shaped JSON after Redis records the terminal (no S3 journal—wire-only stub). Compose defaults this to LocalStack queue **`inspectio-v3-persist`** (created by init). Unset the variable or set it empty to disable.
- **Outcomes:** **`RedisOutcomesStore`** (**`LPUSH` + `LTRIM`** to 100 items per list) shared by **L2** and workers; **`GET /messages/success|failed`** returns newest-first JSON aligned with **`plans/openapi.yaml`** outcome fields.
- **Run:** **`inspectio-v3-worker`** or **`python -m inspectio.v3.worker`**. Requires **`REDIS_URL`** / **`INSPECTIO_REDIS_URL`** and AWS/SQS env consistent with LocalStack.
- **Integration (opt-in):** **`INSPECTIO_REDIS_INTEGRATION=1`** and **`REDIS_URL`** → **`pytest tests/integration/test_v3_redis_outcomes.py -m integration`**.
- **E2E (opt-in):** With **`docker compose up -d`** (L1, api, expander, worker, redis, localstack), **recycle the stack** before the run (see workspace testing rules), then **`INSPECTIO_P4_E2E=1 pytest tests/e2e/test_v3_p4_compose.py -m e2e`**. Defaults to **`http://127.0.0.1:8080`** (L1 proxy). Override with **`INSPECTIO_P4_E2E_BASE`**.

### Deliverables note (master §6, AC5)

- **Structures / sync:** L2 admits **`BulkIntentV1`** to SQS; expander fans out **`SendUnitV1`** to sharded send queues; worker applies absolute deadlines from **`domain/retry_schedule`**, records terminals to Redis, and **deletes** the send-queue message after a terminal outcome.
- **Complexity:** admission **O(1)** per HTTP request; expander **O(N)** in **`count`** for one bulk message; worker **O(1)** per due wakeup per active id (scan of actives).
- **Gaps (AC5):** no **S3** journal or crash recovery for in-flight units—redelivery relies on SQS visibility and worker idempotency/dedupe by **`messageId`** only; multi-replica expander dedupe is still single-process LRU (see P3 README).
- **Planned S3 (later wave):** durable append-only journal for bulk and/or send units, replay and operator inspection—schema TBD in **`plans/V3_ASYNC_PIPELINE_IMPLEMENTATION_PLAN.md`** / OpenAPI evolution.

## V3 L1 static + proxy (phase P5)

- **`inspectio.v3.l1`**: **FastAPI** serves a small **demo UI** at **`GET /`** and **proxies** **`/messages`**, **`/messages/repeat`**, **`/messages/success`**, **`/messages/failed`**, **`/healthz`** to L2 using **`httpx`** (**`INSPECTIO_L2_BASE_URL`**, e.g. **`http://inspectio-api:8000`** on the compose network). Browsers should use **L1 only** (CORS/TLS terminate at L1 in real deploys; compose uses same-origin **`http://127.0.0.1:8080`**).
- **Demo UI:** **Send once** (`POST /messages`) and **Repeat N** with a **single** **`fetch`** to **`POST /messages/repeat?count=N`** (coalesced admission per master plan).
- **Run:** **`uvicorn inspectio.v3.l1.serve:app --host 0.0.0.0 --port 8080`** with **`INSPECTIO_L2_BASE_URL`** set.
- **Tests:** **`pytest tests/integration/test_v3_l1_proxy.py -m integration`** (in-process L1→L2 ASGI chain; matches P5 “light integration” scope).

## V3 Kubernetes (phase P6)

- **Root manifests:** **`deploy/kubernetes/`** — namespace **`inspectio`**, Redis, **L2** Deployment (**`inspectio-api`**, **2** replicas), expander (**1** replica), worker (**1** replica default; duplicate per shard when **`K` > 1**), **L1** (**2** replicas), **ConfigMap** for queue URLs / **`K`** / Redis / **`INSPECTIO_L2_BASE_URL`**, **ServiceAccount** stub for **IRSA**, optional **Secret** pattern (**`secret-aws.example.yaml`** — do not commit real keys).
- **Image:** single **`deploy/docker/Dockerfile`**; set container commands via Deployments (same as compose).
- **Ops:** apply order, **`kubectl set image`**, **`rollout status`**, immutable **selector** notes, probes, multi-shard workers, optional persist queue env — see **`deploy/kubernetes/README.md`** and **`plans/v3_phases/P6_KUBERNETES.md`**.

## V3 load harness (phase P7)

- **Driver:** **`scripts/v3_load_test.py`** — **`httpx`**, **`POST /messages/repeat`**, optional poll **`GET /messages/success`**; **`--max-total-sec 0`** disables the driver wall clock (use Job **`activeDeadlineSeconds`** + **`kubectl wait`**), **`--parallel-admission`**, **`--no-wait-successes`** for admit-only benches.
- **Image:** **`deploy/docker/Dockerfile`** copies **`scripts/`** (same image tag as workloads / Jobs).
- **Jobs:** **`deploy/kubernetes/load-test-job.yaml`** (~**60s** smoke), **`load-test-job-benchmark.yaml`** (minute-scale). **AWS throughput** claims require **in-cluster** runs — not laptop **port-forward** (workspace **`inspectio-full-flow-load-test-aws-in-cluster`**).
- **Outcomes:** v3 repeat returns a **summary**; visibility wait uses **`min(N, limit)`** rows (**≤ 100**). For **N > 100**, use **worker** logs/metrics for **3.1** send completes — see **`deploy/kubernetes/README.md`** and driver JSON fields.
- **Tests:** **`pytest tests/unit/test_v3_load_harness_stats.py -m unit`**.

## V3 persistence contracts (phase P12.0)

- **Contracts only (no runtime behavior changes yet):**
  - **`PersistenceEventV1`** envelope schema (strict validation)
  - **`PersistenceCheckpointV1`** schema
  - deterministic replay ordering helper + idempotent fold reducer scaffolding
- **Tests:** strict schema validation, replay-order determinism, fake transport replay path:
  - **`tests/unit/test_v3_persistence_schemas.py`**
  - **`tests/unit/test_v3_persistence_replay_order.py`**
  - **`tests/integration/test_v3_persistence_fake_transport.py`**
- **Decision lock:** **`plans/v3_phases/P12_DECISION_RECORD.md`**.
- **Load harness extension point:** **`scripts/v3_load_test.py --persistence-mode {off,on}`**
  currently labels benchmark profile only (wiring begins in P12.1+).

## Local stack

The **repository root** `docker-compose.yml` runs **redis**, **localstack** (S3 + SQS), **`inspectio-l1`** (published **8080** → browser entry), **`inspectio-api`** (L2 on **8000** inside the network only—no host port), **`inspectio-expander`**, and **`inspectio-worker`**. Default **`INSPECTIO_V3_SEND_SHARD_COUNT`** is **1** so a single worker covers all send traffic; raise **`K`** and add one worker per **`inspectio-v3-send-{i}`** URL. The v2 app stack remains archived under **`v2_obsolete/archive/`**. Compose project name is **`inspectio`** (`name:` in the file). Stop it with:

```bash
docker compose down
```

Bring it up:

```bash
docker compose up -d
```

| Service              | Host URL / port           |
|----------------------|---------------------------|
| LocalStack           | `http://127.0.0.1:4566`   |
| Redis                | `127.0.0.1:6379`          |
| L1 (browser / demo)  | `http://127.0.0.1:8080`   |

### AWS S3 and credentials

- **Bucket name:** default **`inspectio-test-bucket`**. Override with **`INSPECTIO_S3_BUCKET`** or **`S3_BUCKET`**. Layout for durable state is defined when persistence ships (see **v3 plan** and **ASSIGNMENT.pdf**).
- **Same credentials as the AWS CLI:** Compose injects **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`**, optional **`AWS_SESSION_TOKEN`**, **`AWS_DEFAULT_REGION`**, and **`AWS_ENDPOINT_URL`** into app containers. Defaults **`test` / `test`** and **`http://localstack:4566`** are for LocalStack only.
- Copy **`.env.example`** → **`.env`** and edit, or export variables in your shell before `docker compose up` (e.g. `eval "$(aws configure export-credentials --format env --profile …)"` when your CLI uses SSO or temporary keys). **`.env`** is gitignored.

LocalStack’s init script (**`deploy/localstack/init/ready.d/10-inspectio-aws.sh`**) runs **inside** the LocalStack container and always uses **`aws --endpoint-url=http://localhost:4566`** there; it does not read your laptop’s `~/.aws` unless you extend the image or mount it (not required for normal dev).

Python package: **`pip install -e ".[dev]"`** from repo root (`src/inspectio/`).

### Port conflicts

If another compose stack or local services already bind **6379** or **4566**, stop them before bringing this stack up.

### AWS (EKS) and in-cluster performance

v3 cluster YAML lives under **`deploy/kubernetes/`** (see **`deploy/kubernetes/README.md`**). v2 manifests and the archived load-test driver remain under **`v2_obsolete/archive/deploy/kubernetes/`** and **`v2_obsolete/archive/scripts/`**. Do not treat laptop **`kubectl port-forward`** as authoritative AWS performance claims once v3 Jobs exist (P7).

Local assignment PDF (gitignored): **`plans/ASSIGNMENT.pdf`**.
