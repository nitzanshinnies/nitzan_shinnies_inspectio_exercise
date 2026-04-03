# Plan A — Transport and persistence writer tuning (AI SE)

## Purpose

Improve **persist-on / persist-off completion ratio** and **admit RPS** using **configuration and small, bounded code changes** that do **not** redefine **when** transport messages are acked relative to **S3 durability** (that is **Plan B**).

## Preconditions

- Baseline benchmark completed per `P12_9_AI_SE_PLAN_D_EKS_BENCHMARK_EXECUTION.md` (**`plans/v3_phases/artifacts/p12_9/iter-N/`** + **`ITERn_RESULTS.md`**).
- Branch with writer pipeline (`decoupled_v1`) merged or checked out.
- **`INSPECTIO_V3_PERSIST_DURABILITY_MODE=best_effort`** for tuning iterations unless explicitly testing `strict`.

## Non-goals (this plan)

- Changing **when** transport messages are acked relative to **S3 Put** completion (Plan B).
- Scheduler or L2 API shape changes.
- Reducing shard count or removing persistence transport.

## Evidence-driven hypotheses (from iter-6)

1. **`ack_queue_depth` hundreds** with **`ack_latency_ms` ~1–2s** → **SQS `DeleteMessageBatch`** throughput (default **`persistence_ack_delete_max_concurrency=2`**) may throttle the decoupled ack path.
2. **Flush min batch 64 + interval 2000ms** → batching / timer tradeoff vs completion RPS (direction **not** guaranteed; measure).
3. **Emitter** `max_inflight` / batch sizes on worker → may limit how fast events enter transport under load.

## ConfigMap key reality check

- **`INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY`** is defined in **`deploy/kubernetes/configmap.yaml`** (template default `"2"`). If the **live** EKS ConfigMap **omits** this key, the process uses **`settings.py` default (2)**—you must **`kubectl patch`** or **`apply`** so the key is **present** when tuning.
- Valid range **1..8** enforced in **`SqsPersistenceTransportConsumer`**.

## Task order (blast radius)

Run **A.1** (ack concurrency) **before** **A.2** (flush sweep): fewer moving parts, easier attribution.

## Task A.1 — Raise ack delete concurrency (ConfigMap-first)

**Goal:** Use **`INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY`** (clamped **1..8** in `src/inspectio/v3/persistence_transport/sqs_consumer.py`).

**Steps:**

1. Confirm wiring: `persistence_writer/main.py` passes `ack_delete_max_concurrency=settings.persistence_ack_delete_max_concurrency` into the consumer factory path used at runtime.
2. Ensure the key exists on the cluster: `kubectl -n inspectio get cm inspectio-v3-config -o jsonpath='{.data.INSPECTIO_V3_PERSISTENCE_ACK_DELETE_MAX_CONCURRENCY}'` (empty → add key).
3. Set e.g. **`4`**, then **`8`**, with **full stack recycle** between trials.
4. Run full **240s** A/B per Plan D (short smoke **invalidates** gate claims but may be used for **trend** only—label as such in results).
5. Capture **`writer_snapshot_extract.json`**; expect **`ack_queue_depth_high_water_mark`** / **`ack_latency_ms_max`** to move **if** deletes were the bottleneck.

**Acceptance:** Document before/after in **`ITERn_RESULTS.md`**; no sustained increase in **`flush_failures`**, **`s3_errors`**, or **OOM**; hygiene **`measurement_valid: true`**.

**Rollback:** Revert ConfigMap value; recycle.

## Task A.2 — Flush batching and interval sweep (ConfigMap)

**Goal:** Find a measured Pareto point for **completion RPS** vs writer behavior.

**Knobs:**

- **`INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_MIN_BATCH_EVENTS`** (iter-6 snapshot: **64**)
- **`INSPECTIO_V3_PERSISTENCE_WRITER_FLUSH_INTERVAL_MS`** (iter-6 snapshot: **2000**)

**Steps:**

1. **One dimension at a time** first (e.g. min batch **32 / 64 / 128** at fixed interval), then interval ladder if needed.
2. Full stack recycle + **full** A/B each time (hygiene-locked).

**Acceptance:** **R** (completion ratio %) improves vs previous **`iter-*`** baseline **or** document **no improvement** with evidence; pytest scope green.

**Risk:** Smaller batches → **more** S3 PUTs → completion may **worsen**; do not assume direction.

## Task A.3 — Writer flush-loop sleep and receive parallelism

**Goal:** Bounded flush-loop CPU when idle; optional receive parallelism **≤ 4**.

**Knobs:**

- **`INSPECTIO_V3_WRITER_FLUSH_LOOP_SLEEP_MS`** (default **10** in `settings.py`)
- **`INSPECTIO_V3_WRITER_RECEIVE_LOOP_PARALLELISM`** (default **1** in `settings.py`, max **4**; k8s template sets **`2`**)
- **`INSPECTIO_V3_WRITER_PIPELINE_ENABLE`** must remain **`true`** for decoupled mode.

**Steps:**

1. **`deploy/kubernetes/configmap.yaml`** includes explicit **`PIPELINE_ENABLE`**, **`RECEIVE_LOOP_PARALLELISM`**, and **`FLUSH_LOOP_SLEEP_MS`** so EKS clusters do not rely on implicit defaults. Tune upward (**`3`/`4`**) only when justified by `writer_snapshot` / load.
2. Re-benchmark after change.

## Task A.4 — Persistence emitter limits (worker)

**Goal:** Reduce worker-side backpressure to transport.

**Files:**

- `src/inspectio/v3/settings.py` — `persist_transport_max_inflight_events`, `persist_transport_batch_max_events`, backoff fields.
- `src/inspectio/v3/worker/main.py` — sharded / single producer wiring.

**Steps:**

1. Record **current** EKS values: `kubectl -n inspectio get cm inspectio-v3-config -o yaml`.
2. Increase **`max_inflight`** in **increments**; re-benchmark each step.
3. Watch for memory growth and `best_effort` drop paths (logs / metrics).

## Tests (local, before each push)

**Minimum** pytest set matches **`P12_9_SE_THROUGHPUT_AND_BACKUP_FIX_SPEC.md`** §Tests (writer, settings, fake flow, fault injection, **`test_v3_persistence_transport_sqs_producer`** if producer code paths change, sustained admit).

```bash
cd nitzan_shinnies_inspectio_exercise
pytest -q \
  tests/unit/test_v3_persistence_writer.py \
  tests/unit/test_v3_persistence_writer_main_observability.py \
  tests/unit/test_v3_settings_persistence_writer.py \
  tests/integration/test_v3_persistence_writer_fake_flow.py \
  tests/integration/test_v3_persistence_fault_injection.py \
  tests/unit/test_v3_persistence_transport_sqs_producer.py \
  tests/unit/test_v3_sustained_admit.py
```

Extend tests if bounds or env aliases change.

## Definition of done (Plan A)

- At least one **hygiene-valid** full A/B run in a **new** `iter-N` with **R** and admit ratio vs **prior** `iter-*`.
- **True promotion** only if **all** requirements in **`P12_9_AI_SE_HANDOFF_INDEX.md`** hold, including **manual gate 2** (**(R − 44.84) ≥ 5** — hygiene script **`decision`** is **gate 1 only**). Otherwise **NO-GO** with rollback note.

## References

- `src/inspectio/v3/persistence_transport/sqs_consumer.py`
- `src/inspectio/v3/settings.py` — `persistence_ack_delete_max_concurrency`
- `deploy/kubernetes/configmap.yaml`
- `deploy/kubernetes/README.md` — ConfigMap key table
