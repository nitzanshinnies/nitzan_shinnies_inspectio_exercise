# V2 throughput and EKS load testing — post mortem

This document records **what we built**, **how we measured it on AWS EKS**, **what the numbers showed**, and **what failed or misled us**. It is written for engineers who will pick up **aggregate ingest (N1) targets** (e.g. “tens of thousands of messages per second”) without repeating the same blind alleys.

**Companion implementation:** GitHub PR **#69** (`feat/fast-drain-durability-perf` → `main`) for code; **#70** (`v2-post-mortem` → `main`) stacks this document on the same implementation branch history.

---

## 1. Scope and non-goals

**In scope**

- **Admission throughput:** `POST /messages/repeat` → SQS FIFO `SendMessageBatch` path, as exercised by `scripts/full_flow_load_test.py` **inside** the cluster (normative for AWS claims per repo rules).
- **Infra layout actually used:** cluster name, node group, namespace topology, replica counts at the time of runs.
- **Pitfalls:** scheduling, driver design, documentation framing (ordering), timeout alignment.

**Out of scope (for this post mortem)**

- Proving **10,000+ sustained messages/sec** on the current stack (we did **not** achieve it).
- Laptop `kubectl port-forward` as a performance baseline (explicitly discouraged for AWS throughput claims in workspace rules).

---

## 2. Target architecture (greenfield `inspectio`)

**Ingest boundary:** Amazon SQS **FIFO** queue (`INSPECTIO_INGEST_QUEUE_URL`), `SendMessageBatch` (max **10** entries per call), `MessageGroupId` derived from shard routing (**§16.4**). Parallel send pipelines **across** distinct groups; serialized batches **within** each group in `SqsFifoIngestProducer` (`src/inspectio/ingest/sqs_fifo_producer.py`).

**API:** FastAPI + `aioboto3` SQS client (shared session). Large repeats return full `messageIds` / `shardIds` per blueprint (**§15.2**, **§29.11**).

**Worker:** Long-poll `ReceiveMessage`, Redis idempotency (**§17.4**), S3 journal template A (**§18.3**), then `DeleteMessage`.

**Plans:** `plans/SQS_FIFO_THROUGHPUT_AND_ADMISSION_PLAN.md` describes batch limits, parallelism, and in-cluster validation. **Product NFR:** cross-message **ingest order is not required** (docs updated during this work; journal / outcomes ordering semantics remain separate).

---

## 3. Infrastructure layout (EKS, measurements)

| Item | Value |
|------|--------|
| **Cluster** | `nitzan-inspectio` (EKS, `us-east-1`) |
| **Node group** | `ng-main`, **t3.large**, managed node group |
| **Scaling exercised** | **2 → 4 → 2** nodes (`eksctl scale nodegroup …`) during throughput experiments; **scaled down** afterward |
| **Namespace** | `inspectio` |
| **API** | `Deployment/inspectio-api` — **12 replicas** (baseline); briefly **24** during one experiment; **12** again after scale-down |
| **Workers** | `StatefulSet/inspectio-worker-sts`, **12** replicas; `Deployment/inspectio-worker` also present in cluster |
| **Other** | `inspectio-notification` (4 replicas), `mock-sms` (3), `redis` (1) |
| **Image (throughput work)** | ECR `194768394273.dkr.ecr.us-east-1.amazonaws.com/inspectio-exercise:throughput-20260328201802-amd64` (example tag from build/push during session) |
| **ConfigMap (examples)** | `INSPECTIO_MAX_SQS_FIFO_INFLIGHT_GROUPS=512`, `INSPECTIO_SQS_RECEIVE_CONCURRENCY=8`, `INSPECTIO_INGEST_BUFFER_MAX_MESSAGES=200000` |

**Load driver:** Kubernetes `Job` in `inspectio`, same image as API (includes `scripts/`), `INSPECTIO_LOAD_TEST_API_BASE=http://inspectio-api:8000`, **ClusterIP** Service load-balancing across API pods.

---

## 4. Code and config changes (summary)

Implemented on `feat/fast-drain-durability-perf`:

1. **Homogeneous batch encoding** for repeat-shaped admits: one `bodyHash` + shared payload dict per SQS chunk; verified equivalent to full `MessageIngestedV1` JSON (`tests/unit/test_sqs_fifo_producer.py`).
2. **`orjson`** for `POST /messages/repeat` HTTP body; **`httpx.Limits`** on the API client for internal calls.
3. **Worker:** `INSPECTIO_SQS_RECEIVE_CONCURRENCY` independent long-poll loops per process; **`asyncio.gather`** across messages in each receive batch.
4. **`full_flow_load_test.py`:** `--max-total-sec 0` disables driver wall clock; **`--parallel-admission`** for concurrent `repeat` streams; JSON summary includes cap metadata when set.
5. **Kubernetes:** `load-test-high-parallel-admit-job.yaml`, `n1-admit-bench-job.yaml`; ConfigMap tuning; README performance bullets.
6. **Plans:** ordering reframed as not a product ingest NFR; blueprint **§29.4** env rows for FIFO inflight groups and SQS receive concurrency.

**Tests:** `pytest tests/` — **49 passed** at time of commit.

---

## 5. Measurement methodology

**Rules observed (repo / workspace)**

- **In-cluster** driver only for AWS throughput claims (no port-forward “production” numbers).
- **Full stack recycle** (rollout restart of participating Deployments + worker StatefulSet) before significant load runs when following workspace guidance.

**Driver parameters (admit-focused)**

- **`--no-wait-outcomes`:** measures admission phase without polling outcomes (reduces confounding from notification / terminal indexing).
- **`--max-total-sec 0`:** no artificial driver timeout (align Job `activeDeadlineSeconds` + `kubectl wait` separately).
- **`--parallel-admission N`:** `N` concurrent HTTP clients, each issuing chunked `POST /messages/repeat` (aggregate N1 style).
- **`--chunk-max`:** cap per request `count` (e.g. 2000).

**Metric reported by driver**

- **`admission_rps`:** `size / admission_sec` for the phase — **messages per second** for the aggregate admit window, not HTTP requests/sec.

---

## 6. Results (representative runs)

### 6.1 Smoke (single stream, small N)

- **Shape:** `size=1000`, `parallel_admission=1`, single chunk, with or without outcome wait (job config varied).
- **Observed:** on the order of **~270–400** `admission_rps` depending on run and cluster load; **e2e** dominated by drain when `--wait-outcomes` was enabled.

### 6.2 High parallel, 100k messages (baseline layout: 12 API, 2 nodes → scheduling fix)

**First attempt (failed):** Job requested **4 CPUs**; cluster had **2× t3.large** nodes with **Insufficient cpu**; pod stayed **Pending** until Job `activeDeadlineSeconds` (**30m**) killed the Job (**DeadlineExceeded**). **Pitfall:** high `resources.requests` on Jobs on small clusters.

**Successful run (after fix):** `requests: cpu: 100m`, `limits` higher; **100000** messages, **`--parallel-admission 64`**, **`--chunk-max 2000`**, admit-only.

| Metric | Value (approx.) |
|--------|------------------|
| **`admission_rps`** | **~512** |
| **`admission_sec`** | **~195 s** |
| **`parallel_admission`** | **64** |
| **Chunk latency (p50)** | **~152 s** (per-chunk, under load) |

Interpretation: **10,000 msg/s** was **not** approached; **~500 msg/s** aggregate was the **best** single-driver result in this layout.

### 6.3 Scale-out experiment (4 nodes, 24 API replicas)

- **100k, `parallel_admission=128`:** **`admission_rps` ~391** — **worse** than 64-way on one driver pod. Likely **driver CPU / thread contention** (one process, 128 threads) and/or increased backend contention.
- **Two Jobs × 50k, each `parallel_admission=64`:** per-job **`admission_rps` ~200–205**, wall time **~244–249 s** each — combined stress similar to **~400 msg/s** effective aggregate, not an improvement over the best **~512** case.

**Conclusion from experiments:** **Doubling nodes and API replicas** did not unlock an order-of-magnitude gain; the limiting factors are **not** solely “number of API pods behind the Service.”

---

## 7. Conclusions

1. **~500 msg/s aggregate admit** (100k test, 64 parallel streams, 12 API pods, 2-node baseline) is a **rough empirical ceiling** for the **current** hot path (large `repeat` + full JSON response + SQS FIFO batching + Python asyncio stack) without further **product or architecture** changes.
2. **10,000 msg/s** is **not** a tuning-only goal. It implies **large reductions in per-message work** (especially **response payload** and JSON CPU), **multi-process API** (multiple uvicorn workers per pod), **many distributed load generators** with **moderate** concurrency each, and **substantially larger** AWS compute and queue headroom — and possibly **ingest transport** changes if FIFO constraints are relaxed by spec.
3. **Load-test Job resource requests** must be **small enough to schedule** on the real cluster; prefer **low requests + limits** for driver pods on dev/study clusters.
4. **Very high `parallel-admission` in a single pod** can **hurt** throughput; **many pods × modest parallelism** is the safer mental model.
5. **Documentation** should not treat **FIFO `MessageGroupId` behavior** as a **user ordering promise** unless the product requires it; doing so derails throughput discussions.

---

## 8. Pitfalls checklist

| Pitfall | Symptom | Mitigation |
|--------|---------|------------|
| **High Job `cpu` requests** | Pod **Pending**, Job **DeadlineExceeded** | Use small **requests**, cap with **limits**; check `kubectl describe pod` |
| **Single driver, huge thread count** | Lower `admission_rps` than moderate parallelism | Several Jobs / pods, **8–32** threads each |
| **`kubectl wait --for=condition=complete` on failed Job** | Confusing timeouts | Check `job.status` and pod logs; align `activeDeadlineSeconds` |
| **Port-forward load tests** | Misleading “AWS perf” | Run Job **in cluster** |
| **Ignoring SQS / worker lag** | Admit “succeeds” but queue explodes | Watch **ApproximateAgeOfOldestMessage**, worker CPU, journal flush |
| **Mixing HTTP RPS vs message RPS** | Wrong expectations | Driver `admission_rps` is **messages/sec** for the phase |
| **Outcome `limit` smaller than batch** | Drain never “completes” in driver | **`outcome-limit` / `INSPECTIO_OUTCOMES_MAX_LIMIT` ≥ batch** (see §10.11) |

---

## 9. Suggested next steps (engineering)

1. **Product / blueprint:** optional **summary** or **async id** response for very large `repeat` (requires explicit spec change; today full `messageIds` is locked).
2. **API runtime:** **multiple worker processes** per pod (gunicorn + uvicorn workers) to use **>1 CPU** for CPU-bound JSON and hashing.
3. **Load harness:** **many** in-cluster Job replicas (or k6/Locust) with capped concurrency; **prometheus** or CloudWatch dashboards for admit latency and SQS metrics.
4. **Capacity:** right-size **instance types** (not only replica count); **FIFO throughput** and **account quotas** as hard ceilings.
5. **If ingest order is truly irrelevant:** evaluate **Standard SQS** + explicit **dedupe** story (human waiver of **§17 / §29** FIFO-only ingest).

---

## 10. Gaps and topics a future architect should still validate

The sections above are accurate for **what was run and observed**; they are **not** a complete capacity model. Before betting a design on N1-scale ingest, explicitly close these gaps.

### 10.1 Dual worker surfaces (`Deployment` + `StatefulSet`)

The measured cluster listed both **`Deployment/inspectio-worker`** and **`StatefulSet/inspectio-worker-sts`**. This post mortem **does not** prove whether both attach to the **same** SQS queue, whether one is legacy/unused, or how duplicate consumers interact with **§17.4** Redis dedupe. **Risk:** hidden double-consumption, confusing scale knobs, or masked latency. **Action:** document the **single** supported worker topology for production-like tests; remove or isolate the unused path before drawing firm drain conclusions.

### 10.2 Burstable instances (`t3.large`)

**t3** is **CPU-credit** based. Sustained admit/load can **exhaust credits** and flatten performance in ways that look like “application limits.” The runs here did not include **CloudWatch `CPUCreditBalance`** (or equivalent) in the write-up. **Action:** repeat critical runs on **non-burstable** (e.g. `m6i`, `c6i`) or **unlimited** mode with cost eyes open, and chart credits alongside `admission_rps`.

### 10.3 Observability baseline (missing artifacts)

We cite **driver JSON** and qualitative checks; we did **not** archive a standard dashboard set for:

- SQS: **`ApproximateNumberOfMessagesVisible`**, **`ApproximateAgeOfOldestMessage`**, throttles on `SendMessageBatch` / `ReceiveMessage`
- API: per-pod CPU/memory, **p95/p99 server-side latency** for `/messages/repeat` (if instrumented)
- Redis: memory, evictions, command latency
- S3: journal **`PutObject`** rates / throttles per prefix

**Action:** define a **minimal metric bundle** for any future “we hit X msg/s” claim.

### 10.4 Workload shape (payload size and realism)

Load tests used a **small fixed `body`**. **Larger bodies** inflate JSON, SQS payload size, hashing, and network bytes per message; **`admission_rps` will drop** without any code change. **Action:** bracket tests with **min / typical / max** body sizes from the product.

### 10.5 End-to-end path vs admit-only

Most high-load numbers here are **admit-only** (`--no-wait-outcomes`). **Drain** involves workers, **S3 journal**, **mock-sms**, notification, and outcomes indexing — any of which can become **the** bottleneck while admit still looks “fine.” **Action:** run paired tests: **admit SLO** and **e2e time-to-terminal** under the same offered load.

### 10.6 Statistical rigor and regression baseline

Reported **`admission_rps`** are from **single or few runs** on a shared dev/study cluster; **variance**, **time-of-day**, and **queue backlog state** at test start were not controlled. There is no **A/B** “before vs after homogeneous encoding” on identical infra in this document. **Action:** for regressions, store **N runs**, median/IQR, and **commit SHA + image digest** per row.

### 10.7 External ingress vs in-cluster Service

Tests targeted **`ClusterIP`** `inspectio-api` from inside the namespace. **ALB/NLB**, **TLS**, **HTTP/2**, and **idle timeouts** can change **client-visible** throughput and error modes. **Action:** if production admits through ingress, add an **in-VPC but through ingress** phase (still not laptop port-forward).

### 10.8 Config coupling (`INSPECTIO_WORKER_REPLICAS` vs StatefulSet)

**§29 / deploy README** require **`INSPECTIO_WORKER_REPLICAS`** to match **StatefulSet `spec.replicas`** for shard ownership consistency. Scaling workers **only** in one place is a **correctness** pitfall unrelated to RPS but lethal for replay/snapshots. **Action:** treat this as a **pre-flight checklist** item on every scale test.

### 10.9 Idempotency key volume

Large repeats create **O(N)** Redis keys (`SET NX`, TTL). At very high sustained rates, **memory**, **key cardinality**, and **RDB/AOF** behavior matter. **Action:** model **peak keys** and **Redis maxmemory** policy for worst-case bursts.

### 10.10 Synthetic downstream (mock SMS)

End-to-end behavior in this stack uses **mock-sms**, not carrier latency or external quotas. **Conclusions about “system throughput”** are about **this exercise topology**, not SMS vendor reality.

### 10.11 Outcomes API limits vs drain tests

When using **`--wait-outcomes`**, the driver polls **`GET /messages/success`** and **`/messages/failed`** with an **`outcome-limit`** (and the API clamps to **`INSPECTIO_OUTCOMES_MAX_LIMIT`**). If **`limit < batch size`**, polling can **miss** terminals that rolled off the “last N” window, producing **false negatives** (looks like incomplete drain). **Action:** for e2e load tests, set **outcome limit ≥ admitted batch** (or change the driver to track by id without relying on truncated lists).

### 10.12 Single-process API (`uvicorn` / asyncio)

Each API pod ran a **single** Uvicorn worker in these tests. CPU-heavy work (**orjson**, hashing, building huge `messageIds` arrays) contends on **one event loop per pod** unless you add **multiple processes** per Deployment pod. **Action:** treat “more replicas” and “more cores per pod” as **independent** knobs; profile **one pod under `repeat`** with `top`/`py-spy` before scaling horizontally only.

### 10.13 Kubernetes and VPC networking under churn

High **connection counts** (many parallel `httpx` clients × many pods) can stress **CoreDNS**, **conntrack** tables, and **kube-proxy** behavior before AWS limits bite. Symptoms: **intermittent** `ConnectTimeout`, elevated DNS latency, **5xx** from the client perspective with healthy app logs. **Action:** for extreme RPS tests, monitor **node-level** network metrics and consider **NodeLocal DNSCache** or **prefix delegation** tuning per your EKS guide — not investigated in this post mortem.

### 10.14 SQS visibility timeout and redelivery

Under worker or journal slowness, **visibility timeout** expiry causes **redelivery**. **§17.4** dedupe should collapse duplicates, but **extra SQS API volume** and **journal noise** still cost money and confuse operators. **Action:** align **visibility timeout** with **p99 journal flush + handler** time; watch **receive/delete ratio** and **duplicate** idempotency hits during overload.

### 10.15 Cost and blast radius of experiments

Scaling the node group **2 → 4** (even briefly) and raising API replicas **12 → 24** has **real AWS cost**. The exercises here were on a **shared study cluster**; results may include **noisy neighbors** (other workloads) unless the namespace is dedicated. **Action:** tag resources, cap **max nodes** in Terraform/eksctl, and record **account/region** when comparing runs across teams.

### 10.16 FIFO deduplication window

SQS FIFO uses a **deduplication interval** (on the order of **minutes**) for `MessageDeduplicationId`. Bursts of **retries** or **replay tests** inside that window can **suppress** legitimate sends if keys collide by mistake. **Action:** load and chaos tests should use **fresh idempotency keys** per logical message unless explicitly testing dedupe.

---

## 11. Revision history

| Date (UTC) | Author / context | Note |
|------------|------------------|------|
| 2026-03-29 | Agent session closeout | Initial post mortem from EKS experiments and code review |
| 2026-03-29 | Architect review pass | Added §10 gaps (dual worker, t3 credits, observability, payload shape, e2e vs admit, statistics, ingress, worker replica coupling, Redis keys, mock SMS) |
| 2026-03-29 | Second pass | §10.11–10.16: outcomes limit, uvicorn single-process, k8s networking, SQS visibility/redelivery, cost/blast radius, FIFO dedupe window; PR #69/#70 pointers |
