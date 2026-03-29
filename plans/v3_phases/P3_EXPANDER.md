# P3 — Expander (bulk → N units, sharded SQS)

**Goal:** L3 broker: consume **`BulkIntentV1`**, emit **N** **`SendUnitV1`** to **K standard send queues**, **`stable_hash(messageId) % K`** (**4.3**). **Idempotent** w.r.t. SQS redelivery (**4.2**).

**Needs:** P2.

**Refs:** master **3.2** (O(N) work here is OK; L2 admission stays O(1) in N); **8** observability (log **`traceId`**, **`batchCorrelationId`**, **`messageId`**, **`shard`**; counter **`expanded`**).

## Done when

- [ ] **K** queues + settings: **`INSPECTIO_V3_SEND_SHARD_COUNT`**, URL list or prefix (**4.3**). **Standard** queues unless human locks **FIFO** (FIFO complicates **10k/s**, **3.1**).
- [ ] Long-poll **`ReceiveMessage`** → parse bulk → **N** new UUID **`message_id`** → **`SendUnitV1`** (`attemptsCompleted=0`, **`receivedAtMs`** from bulk) → **`SendMessageBatch`** (chunks of 10) → **`DeleteMessage`** bulk receipt **only** after all publishes succeed; on partial failure, rely on visibility timeout + retry (**document**).
- [ ] **Dedupe** so duplicate bulk delivery does not create **2N** units: in-process LRU OK for **one** expander replica; **Redis SETNX** (or equivalent) if multiple expander replicas—**document** chosen mode.
- [ ] **`shard_for_message_id`**: stable int in **`[0, K)`** (e.g. SHA-256 of id).
- [ ] **Unit:** shard stability, batch chunking; **integration:** bulk **count=3** → three sends on expected shards.
- [ ] Logs/metrics per master **8** where cheap (**`sqs_throttle`** on publish retries if applicable).

## Layout (suggested)

`v3/expander/main.py`, `consumer.py`, `publish.py`, `dedupe.py`.

## Out of scope

**`try_send`**, HTTP, outcomes store.

**Next:** P4 send workers consume **`SendUnitV1`**, **batch receive** where helpful (**7.2**).
