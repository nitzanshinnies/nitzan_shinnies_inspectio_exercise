# Ingest without Kinesis: design change plan

**Status:** implemented (see **`src/inspectio/ingest/sqs_fifo_*.py`**, **`ingest_consumer.py`**)  
**Created:** 2026-03-26  
**Trigger:** interviewer-provided AWS account is blocked from **Amazon Kinesis Data Streams** by **Organizations SCP** (e.g. `CreateStream`, `ListStreams` denied).

This document was the **migration plan** for replacing Kinesis with **SQS FIFO**. Normative behavior is reflected in **`plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** and code; keep **§18.3** (journal before **`DeleteMessage`**).

---

## 1. Goals and non-goals

### 1.1 Goals

- Preserve the **intent** of the ingest path: **durable handoff** from API to worker, **at-least-once** delivery, **idempotent** application to journal/state, and **no checkpoint advance** until **§18.3** is satisfied for that ingest.
- Use only AWS APIs that remain **allow-listed** under typical interview SCPs (**SQS** and **S3** are the usual safe choices).
- Keep **single-worker default** (§29.6) as the simple path; document how to scale later without silent duplication bugs.
- Update **blueprint / phases / runbooks** so agents and humans are not told to use Kinesis when the account forbids it.

### 1.2 Non-goals (this plan)

- Full implementation (producer, consumer, Terraform, CI matrix).
- Changing **business** semantics of `POST /messages` / repeat flows beyond what ingest replacement requires.
- Guaranteeing **global** ordering across all messages (only **per logical shard** ordering was encoded via Kinesis partition keys).

---

## 2. Current architecture (Kinesis) — what must be replaced

| Concern | Kinesis behavior today | Notes |
|--------|-------------------------|--------|
| API | `PutRecords` (batch up to **500**) | `kinesis_producer.py` |
| Durability | Stream retains records until worker consumes + checkpoints | |
| Ordering | **Per partition key** (`shard_id` as zero-padded decimal) | TC-STR-003 |
| Worker | Poll `GetRecords`, process, **journal + flush**, then **checkpoint** | `kinesis_consumer.py`, §18.3 |
| Checkpoint | S3 object per **Kinesis shard id** + sequence number | `INSPECTIO_KINESIS_CHECKPOINT_KEY_PREFIX` |
| Failure | Retry reads; unprocessed records remain in stream | |

**Load-test observation:** without a real stream (or compatible emulator), admission fails and routes such as **`POST /messages/repeat`** can return **503** / `ingest_unavailable` — consistent with Kinesis being the required backbone.

---

## 3. Replacement options (decision)

### 3.1 Shortlist

| Option | Pros | Cons |
|--------|------|------|
| **A. SQS FIFO queue** | **MessageGroupId** ≈ Kinesis partition key → **per-shard ordering**; **deduplication** optional (DeduplicationId); DLQ + redrive; no Kinesis | Lower batch size (**10** msgs per `SendMessageBatch`); FIFO throughput limits per group; different checkpointing model |
| **B. SQS standard queue** | Very high throughput; simple | **No** per-shard ordering; duplicates more visible; spec change if ordering was relied on |
| **C. DynamoDB “outbox” table** | Full control, conditional writes | More application code; streams + consumers or polling; higher design surface |
| **D. SNS → SQS** | Fan-out | Extra hop; ordering still ends up in SQS semantics |

**Recommendation:** **Option A — one SQS FIFO queue** (primary ingest) + **dead-letter queue (DLQ)** (FIFO or standard per ops preference) for poison messages.

**Rationale:** The blueprint ties **partition key** to **`shardId`** for ordering and test IDs (TC-STR-003). **FIFO + `MessageGroupId = f"{shard_id:05d}"`** preserves that **per-shard** ordering property without Kinesis. Standard queues do not.

**If** product owners accept **unordered** ingest across shards, **Option B** reduces cost and complexity; treat that as an explicit **spec relaxation** with test updates.

### 3.2 What FIFO does *not* replicate

- **Kinesis sequence numbers** as a global cursor: replaced by **SQS** `MessageId` + `ReceiptHandle`, and **delete-on-success** after §18.3.
- **500-record API batches:** FIFO batches are capped at **10** messages per `SendMessageBatch`. API layer may need **more round-trips** or **concurrent sends** (with backoff) for the same admission rate — document in performance notes.

---

## 4. Target architecture (SQS FIFO)

### 4.1 Components

1. **Ingest FIFO queue**  
   - **Message body:** same JSON as today’s wire format (`MessageIngestedV1` / existing schema) — minimize churn.  
   - **`MessageGroupId`:** `partition_key_for_shard(shard_id)` (same string as Kinesis partition key).  
   - **`MessageDeduplicationId`:** derive from **`idempotency_key`** (or a stable hash if length limits apply) to reduce duplicate enqueues when the API retries HTTP.

2. **DLQ**  
   - Redrive policy after **N** receives or **maxReceiveCount** (tune with worker processing time).  
   - Operational path: inspect DLQ, fix bug, replay (script or console).

3. **API (producer)**  
   - Replace `KinesisIngestProducer` with **`SqsFifoIngestProducer`** (name indicative) using `send_message` / `send_message_batch`.  
   - Map AWS errors to existing **`IngestUnavailableError`** semantics where appropriate.

4. **Worker (consumer)**  
   - Replace Kinesis poll loop with **long polling** `receive_message` (wait seconds ≤ 20, batch size ≤ 10 for FIFO).  
   - For each message: decode → **`KinesisIngestConsumer.process_record`** equivalent — preferably **rename / generalize** `KinesisRawRecord` to **`IngestRawRecord`** (fields: `data`, opaque `cursor` for checkpoint).  
   - **§18.3 ordering:** append + flush journal lines **before** deleting the message from SQS.  
   - **Commit:** `DeleteMessage` (receipt handle) **after** journal flush succeeds. This is the SQS analogue of “advance checkpoint only after durability.”

5. **Checkpoint store (S3)**  
   - **Kinesis-specific** checkpoint files (per Kinesis shard id + sequence number) become **optional** or **replaced**:  
     - **Minimal:** rely on SQS visibility + at-least-once + idempotent handler (already required).  
     - **Paranoid / multi-worker future:** store **last completed `message_id` per MessageGroupId** in S3 for debugging or stricter dedupe — **not** required for single-worker FIFO if delete-after-journal is correct.

### 4.2 Protocol / env changes (illustrative)

| Today | Proposed |
|-------|----------|
| `INSPECTIO_KINESIS_STREAM_NAME` | `INSPECTIO_INGEST_QUEUE_URL` (FIFO queue URL) |
| `INSPECTIO_KINESIS_CHECKPOINT_KEY_PREFIX` | `INSPECTIO_INGEST_CHECKPOINT_KEY_PREFIX` **or** remove if checkpoints simplified |
| Worker IAM: `kinesis:Get*`, `PutRecords` (API), etc. | `sqs:SendMessage*`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes`, DLQ permissions |

**OpenAPI / error codes:** keep **`ingest_unavailable`** when SQS is unreachable; document queue URL misconfiguration.

### 4.3 Local and CI

- **LocalStack:** SQS is widely supported; **FIFO** support varies by version — verify in `deploy/localstack` init scripts or pin LocalStack version.  
- **Alternative:** **ElasticMQ**, **moto** in tests, or in-memory fake implementing the **same producer/consumer protocols** as today.

---

## 5. Blueprint and governance

The locked agent contract in **§29** currently mandates **Kinesis-only** ingest and lists **replacing Kinesis with SQS** as out of scope. This design change **requires**:

1. A **written waiver** or **revision** to **§29** (and cross-references in **§17**, file manifest, env table) stating **SQS FIFO** (or chosen option) as the durable ingest boundary.  
2. Update **`plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`** and **`plans/IMPLEMENTATION_PHASES.md`** so new work does not reintroduce Kinesis-only assumptions.  
3. Update **`deploy/kubernetes/*`**, **Terraform** (if any), and **IAM example policies** for SQS instead of Kinesis.

---

## 6. Implementation phases (suggested)

### Phase 0 — Agreement

- [ ] Confirm **FIFO vs standard** (ordering requirement).  
- [ ] Confirm **interview AWS account** allows **SQS** APIs (list/create queue in console or CLI).  
- [ ] Merge blueprint amendments (human PR).

### Phase 1 — Abstractions

- [ ] Introduce **neutral protocols** (`IngestProducer`, `IngestConsumer` / record type) if not already present; keep Kinesis impl behind a flag until cutover.  
- [ ] Unit tests: producer batching limits (FIFO **10**), error mapping, consumer **journal-before-delete** order.

### Phase 2 — SQS implementation

- [ ] Implement SQS FIFO producer + consumer.  
- [ ] Wire **Settings** to queue URL + region.  
- [ ] **Idempotency:** ensure duplicate SQS deliveries do not corrupt state (existing dedupe path).

### Phase 3 — Infrastructure

- [ ] IaC or documented console steps: FIFO queue, DLQ, redrive, IAM policy for API vs worker.  
- [ ] Remove or gate Kinesis resources in **LocalStack** init; add SQS queue creation.

### Phase 4 — Validation

- [ ] Docker compose full stack with SQS (or emulator).  
- [ ] **In-cluster** load test job updated: no Kinesis assumptions; health checks unchanged except env.  
- [ ] **§29.6** multi-worker: document “still forbidden by default” or add **lease** design if scaling is in scope.

---

## 7. Risk register

| Risk | Mitigation |
|------|------------|
| FIFO throughput per message group | Measure; shard spread adds parallelism; document API batching change |
| Duplicate messages | Idempotent worker; optional dedupe id on send |
| LocalStack FIFO gaps | Pin version or use alternative emulator |
| Drift from PDF “Kinesis” wording | One paragraph in README: “exercise uses SQS FIFO as durable stream” |

---

## 8. Files likely to change (implementation later)

- `src/inspectio/ingest/kinesis_producer.py` → add `sqs_fifo_producer.py` (or rename module namespace to `ingest/`)  
- `src/inspectio/ingest/kinesis_consumer.py` → generalize + `sqs_fifo_consumer.py`  
- `src/inspectio/settings.py` — env vars  
- `src/inspectio/worker/main.py` (or equivalent) — poll loop  
- `deploy/localstack/init/**`  
- `deploy/kubernetes/*.yaml` — env  
- Tests under `tests/` mirroring ingest  
- `plans/NEW_SYSTEM_IMPLEMENTATION_BLUEPRINT.md`, `plans/IMPLEMENTATION_PHASES.md`

---

## 9. References

- In-repo: **`src/inspectio/ingest/kinesis_producer.py`**, **`kinesis_consumer.py`**, **`inspectio/settings.py`**, worker entrypoint.  
- Blueprint: **§17**, **§18.3**, **§29**, env table (Kinesis checkpoint prefix).  
- AWS: [SQS FIFO queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/FIFO-queues.html) (ordering, batch limits, deduplication).

---

## 10. Commit message suggestion (this branch)

```text
docs: plan ingest migration from Kinesis to SQS FIFO (SCP-safe)

Adds INGEST_WITHOUT_KINESIS_DESIGN_PLAN.md with rationale, target
architecture, env/IAM deltas, phases, and blueprint waiver notes for
accounts where Kinesis is denied by Organizations SCP.
```
