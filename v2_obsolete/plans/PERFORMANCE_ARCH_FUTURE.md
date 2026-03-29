# Performance — larger architectural options (do not lose)

These are **not** implemented in the default greenfield path; they trade blueprint constraints, operational complexity, or correctness surface area for throughput. Revisit when **durability + performance** dominate. **Ingest message order is not a product NFR** (see **`SQS_FIFO_THROUGHPUT_AND_ADMISSION_PLAN.md`**); options below still require **§17 / §29** review when they change the durable boundary or shard routing.

## 1. Ingest transport

- **Standard SQS queue (non-FIFO)** for admission: different dedupe and at-least-once story than FIFO; requires a **human waiver** of **§17 / §29** FIFO-only ingest and new tests.
- **Fewer, coarser `MessageGroupId`s** (e.g. hash to **N** hot groups instead of per-shard): increases **per-group contention**; must remain consistent with **worker shard ownership** (**§16.3**) and **§29.6** scaling rules.

## 2. Journal and recovery

- **Fewer `JournalRecordV1` lines** on the hot path (e.g. combine metadata): must still satisfy **§18.3** delete-after-durable rules and replay tests.
- **Larger segments / async flush** with explicit **fsync/ack** policy: risk window between buffer and S3 visibility; needs a defined **crash story** and tests.

## 3. Read models

- **Outcomes index** (Redis lists) as **purely best-effort**: terminal truth remains **S3 journal**; API could **poll or stream** from journal for “strict” views (heavy operational cost).

## 4. AWS operations

- **S3 request rates** per prefix; **SQS high-throughput FIFO**; **regional quotas** and **Organizational SCPs** (e.g. IAM limits) — performance work often ends here; measure **Throttling** / **SlowDown** before more app changes.

When picking one of the above, update **tests**, **runbook**, and any **§29** waiver in writing.
