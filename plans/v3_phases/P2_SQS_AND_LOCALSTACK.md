# P2 — SQS bulk producer, LocalStack

**Goal:** Enqueue **`BulkIntentV1`** to **SQS** (**4.3**); **standard** bulk queue by default (master plan **L3**, architecture section **2** — FIFO only if human requires). Throttle backoff **unit-tested**. Optional **L5** stub: **`INSPECTIO_V3_PERSIST_QUEUE_URL`** no-op producer only if you introduce the interface early (**4.3**, **L5** stub).

**Needs:** P1.

**Refs:** **4.2** (at-least-once → expander dedupe in P3); **6** agent rules (SQS required, no Kinesis).

## Done when

- [ ] LocalStack init creates **bulk** queue; **`INSPECTIO_V3_BULK_QUEUE_URL`** (+ **`AWS_ENDPOINT_URL`** when local) in settings/README.
- [ ] **`SqsBulkEnqueue`**: JSON body, **`SendMessage`**, shared **aioboto3** session per process.
- [ ] Backoff + jitter on throttling errors (**unit** with mocks).
- [ ] **integration** tests against LocalStack (env-gated if CI has no Docker).
- [ ] Optional: create **send** queue names/URLs placeholder for P3.

## Layout (suggested)

`v3/sqs/client.py`, `bulk_producer.py`, `backoff.py`.

## Tests

| Marker | Cover |
|--------|--------|
| unit | backoff curve + cap |
| integration | send → receive → parse **`BulkIntentV1`** |

## Pitfalls

SQS is **at-least-once**; P3 must not double-expand a bulk. Do not hardcode LocalStack in library code—**endpoint from settings**.

## Out of scope

Expander loop, send-worker scheduler.

**Next:** P3 **`ReceiveMessage`** bulk, **`DeleteMessage`** after N shard publishes.
