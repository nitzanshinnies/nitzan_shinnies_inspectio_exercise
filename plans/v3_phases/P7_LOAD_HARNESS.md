# P7 — Load harness (in-cluster only for AWS claims)

**Goal:** Measure master plan **3.1** **primary metric**: **completed in-process `send` / `try_send` attempts per second** (aggregate) after dequeue, over a steady window; report **p50/p99** and setup. **Burst** target: one **`count≈10 000`** admit driving **~10 000** completions in **~1 s** is **stretch SLO** (**3.1**). **Admission** **RPS** is a **separate** metric (**3.2**).

**Needs:** P6 (or equivalent cluster) + P4 worker path.

**Refs:** **`inspectio-testing-and-performance`** + **`inspectio-full-flow-load-test-aws-in-cluster`** (no laptop **port-forward** baseline); methodology only from **`v2_obsolete/archive/scripts/`**—**rewrite**, do not import.

## Done when

- [x] Driver (e.g. **`scripts/v3_load_test.py`**) + **`httpx`**: admit (**repeat** once or controlled concurrency), optional wait for completion; report **send-side throughput** (master **7.2** “**send RPS**”) per **3.1**, not admission alone. Flags **`--max-total-sec 0`**, timeouts aligned with Job caps.
- [x] **Kubernetes Job** YAML under **`deploy/kubernetes/`**: **`activeDeadlineSeconds`** and **`kubectl wait`** **~60s** for smoke; separate benchmark YAML with **minute-scale** caps if needed—**5**, workspace rules.
- [x] **Dockerfile** copies driver into the **same** image tag the Job uses (or documented alternative).
- [x] **Completion detection:** if **`GET /messages/success`** **`limit=100`**, **N > 100** needs **worker metrics/logs** or another strategy—**document** one approach (**3.1** prefers worker-side **send** counting).
- [x] **Recycle** full stack before benchmarks (workspace **restart-containers** / EKS rollouts).
- [x] **README:** AWS numbers only from in-cluster runs; instance types / replicas.

## Tests

**Unit:** parse args, rate math (`inspectio.v3.load_harness.stats` + **`tests/unit/test_v3_load_harness_stats.py`**). **Local compose smoke** does **not** justify AWS throughput claims.

## Out of scope

k6/Gatling clusters unless requested.
