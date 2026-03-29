# Inspectio exercise

Implementation targets **v3** only. **Normative docs:** **`plans/ASSIGNMENT.pdf`** (local, gitignored), **`plans/openapi.yaml`**, **`plans/V3_ASYNC_PIPELINE_IMPLEMENTATION_PLAN.md`**. **Do not** copy or import legacy code paths — see **`.cursor/rules/inspectio-implementation-no-legacy.mdc`**.

- **`v2_obsolete/plans/`** — archived **v2** specifications and the **V2 EKS throughput post mortem** (historical only).
- **`v2_obsolete/archive/`** — frozen **v2 implementation**: `src/inspectio`, `tests`, `scripts`, `deploy/docker`, `deploy/mock-sms`, `deploy/kubernetes` (see **`v2_obsolete/archive/README.md`**).

## V3 package (phase P0)

- **`inspectio.v3`** lives under **`src/inspectio/v3/`**: queue envelopes **`BulkIntentV1`** / **`SendUnitV1`** (Pydantic, JSON aliases `schemaVersion`, `traceId`, `batchCorrelationId`, `receivedAtMs`, `attemptsCompleted` = **0** before the first `try_send`), pure **`domain/retry_schedule`** (deadlines at **0, 500, 2000, 4000, 8000, 16000** ms after `receivedAtMs`), and **`assignment_surface`** (`Message`, **`try_send` → `bool`**, void **`send`** wrapper). Verify with **`pytest -m unit`**.

## V3 L2 (phase P1)

- **`inspectio.v3.l2`**: FastAPI app from **`create_l2_app`** — **`POST /messages`** and **`POST /messages/repeat?count=`** each enqueue **one** **`BulkIntentV1`** (single path uses **`count=1`**). **`Idempotency-Key`** with in-process TTL (no second enqueue on replay; **409** if the key is reused with a different payload). Repeat responses use the **summary** shape in **`plans/openapi.yaml`** (`batchCorrelationId`, `count`, `accepted`). **`GET /messages/success|failed`** return **`{"items": []}`** until P4 + shared outcomes store. Inject **`clock_ms`** and a **`ListBulkEnqueue`** or **`SqsBulkEnqueue`**; **`BulkEnqueuePort.enqueue`** is **async** (P2 **`aioboto3`**).

## V3 SQS (phase P2)

- **Standard bulk queue** (not FIFO) for **`BulkIntentV1`**: LocalStack init creates **`inspectio-v3-bulk`** (override with **`INSPECTIO_V3_BULK_QUEUE_NAME`**) and **`inspectio-v3-send-0` … `send-(K-1)`** for **`K` = `INSPECTIO_V3_SEND_SHARD_COUNT`** (default **2** in compose).
- **Environment:** **`INSPECTIO_V3_BULK_QUEUE_URL`** (required for real enqueue), **`AWS_ENDPOINT_URL`** (e.g. `http://127.0.0.1:4566` against compose LocalStack), **`AWS_DEFAULT_REGION`**, **`AWS_ACCESS_KEY_ID`** / **`AWS_SECRET_ACCESS_KEY`** (defaults **`test`/`test`** for LocalStack). Use **`build_sqs_bulk_enqueue_from_env()`** from **`inspectio.v3.settings`** or construct **`SqsBulkEnqueue`** manually.
- **Integration test (opt-in):** with LocalStack healthy, set **`INSPECTIO_SQS_INTEGRATION=1`** and **`INSPECTIO_V3_BULK_QUEUE_URL`** to your queue URL (example: `http://127.0.0.1:4566/000000000000/inspectio-v3-bulk`), then run **`pytest tests/integration/test_v3_sqs_bulk_roundtrip.py -m integration`**. CI without Docker leaves these unset so the test is skipped.

## V3 expander (phase P3)

- **`inspectio.v3.expander`**: long-poll **`INSPECTIO_V3_BULK_QUEUE_URL`**, parse **`BulkIntentV1`**, emit **N × `SendUnitV1`** with **`stable_hash(messageId) % K`** routing to **`INSPECTIO_V3_SEND_QUEUE_URLS`** (comma-separated, length must equal **`INSPECTIO_V3_SEND_SHARD_COUNT`**). **`SendMessageBatch`** (chunks of 10) per shard; throttle-style batch failures retry with the same backoff helper as P2. **`DeleteMessage`** on the bulk receipt only after all publishes succeed; if publish fails, the bulk message becomes visible again after **`INSPECTIO_V3_BULK_VISIBILITY_TIMEOUT`** (visibility timeout on receive).
- **Dedupe (single replica):** in-memory LRU of bulk **SQS `MessageId`** after successful publish; redelivery after publish skips fan-out and only deletes (multi-replica dedupe would use **Redis `SETNX`** — not implemented here).
- **Run:** **`inspectio-v3-expander`** (console script) or **`python -m inspectio.v3.expander`** with env set.
- **Integration (opt-in):** **`INSPECTIO_EXPANDER_INTEGRATION=1`**, LocalStack queues created, then **`pytest tests/integration/test_v3_expander_roundtrip.py -m integration`**.

## Local stack

The **repository root** `docker-compose.yml` currently runs **dependencies only**: **redis** and **localstack** (S3 + SQS). The v2 app containers were removed from compose when the code was archived; see **`v2_obsolete/archive/`** for the old stack. Compose project name is **`inspectio`** (`name:` in the file). Stop it with:

```bash
docker compose down
```

Bring it up:

```bash
docker compose up -d
```

| Service    | Host URL / port |
|------------|-----------------|
| LocalStack | `http://127.0.0.1:4566` |
| Redis      | `127.0.0.1:6379` |

### AWS S3 and credentials

- **Bucket name:** default **`inspectio-test-bucket`**. Override with **`INSPECTIO_S3_BUCKET`** or **`S3_BUCKET`**. Layout for durable state is defined when persistence ships (see **v3 plan** and **ASSIGNMENT.pdf**).
- **Same credentials as the AWS CLI:** Compose injects **`AWS_ACCESS_KEY_ID`**, **`AWS_SECRET_ACCESS_KEY`**, optional **`AWS_SESSION_TOKEN`**, **`AWS_DEFAULT_REGION`**, and **`AWS_ENDPOINT_URL`** into app containers. Defaults **`test` / `test`** and **`http://localstack:4566`** are for LocalStack only.
- Copy **`.env.example`** → **`.env`** and edit, or export variables in your shell before `docker compose up` (e.g. `eval "$(aws configure export-credentials --format env --profile …)"` when your CLI uses SSO or temporary keys). **`.env`** is gitignored.

LocalStack’s init script (**`deploy/localstack/init/ready.d/10-inspectio-aws.sh`**) runs **inside** the LocalStack container and always uses **`aws --endpoint-url=http://localhost:4566`** there; it does not read your laptop’s `~/.aws` unless you extend the image or mount it (not required for normal dev).

Python package: **`pip install -e ".[dev]"`** from repo root (`src/inspectio/`).

### Port conflicts

If another compose stack or local services already bind **6379** or **4566**, stop them before bringing this stack up.

### AWS (EKS) and in-cluster performance

v2 Kubernetes manifests and the load-test driver are under **`v2_obsolete/archive/deploy/kubernetes/`** and **`v2_obsolete/archive/scripts/`**. **`deploy/kubernetes/README.md`** describes how v3 will replace them. Do not treat laptop **`kubectl port-forward`** as authoritative AWS performance claims once v3 Jobs exist.

Local assignment PDF (gitignored): **`plans/ASSIGNMENT.pdf`**.
