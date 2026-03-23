# API_PERFORMANCE_OPTIMIZATION.md - High-volume send-path performance plan

Aligned with `plans/SYSTEM_OVERVIEW.md`, `plans/REST_API.md`, `plans/NOTIFICATION_SERVICE.md`, and observed behavior from AWS EKS load runs on 2026-03-23.

## 1) Purpose

Define a concrete optimization plan for `POST /messages/repeat` at high volume (10k+), based on runtime evidence, so the system can:

- accept large batches without client disconnects;
- drain pending state reliably to terminal lifecycle state;
- preserve existing correctness guarantees (integrity checks, lifecycle invariants, and notification publication).

## 2) Observed findings (evidence summary)

### 2.1 What was measured

- AWS EKS deployment with S3 persistence.
- Load driver: `scripts/full_flow_load_test.py` in `--aws` mode.
- Test sizes attempted: smoke (5/10), 2k, 5k, 8k, 10k (and attempted 10k/20k/30k).
- Cross-checked with `kubectl` events/logs/top and per-service performance logs.

### 2.2 Confirmed bottlenecks

1. **Send-path timeout envelope for large synchronous submit**
   - `POST /messages/repeat?count=10000` repeatedly failed at ~61s from the client side (`RemoteProtocolError`).
   - API performance logs showed long request times for `/messages/repeat` (e.g. ~58s and ~76s for high-count runs).
   - This indicates request-path work is too heavy for one synchronous call at high counts.

2. **API -> worker activation adds significant latency**
   - API logs repeatedly showed activation warnings/timeouts:
     - `worker batch activation failed ... httpx.ReadTimeout`
   - Worker activation endpoint latencies were often in multi-second to tens-of-seconds range.

3. **Persistence was a major reliability issue initially, then improved with probe tuning**
   - Before tuning: liveness/readiness probe timeouts caused persistence restarts under load.
   - After probe tuning (`timeoutSeconds=5`, higher failure threshold): no restart loop in follow-up runs.
   - Persistence still contributes load, but is no longer the only or primary bottleneck.

4. **Notification path is active but not dominant for submit failures**
   - Notification publish requests (`/internal/v1/outcomes`) were mostly successful with moderate latency (sub-second to ~1s bursts).
   - No systemic notification instability correlated with submit failure point.

## 3) Current hypothesis

The dominant failure mode for large batches is **synchronous orchestration in the API request lifecycle**, especially activation fanout and downstream coupling, not raw persistence write speed alone.

In short:

- API submit path is doing too much before returning.
- Worker activation latency amplifies submit latency.
- Persistence probe instability was a secondary blocker (now partially addressed).

## 4) Goals

### 4.1 Primary goals

- Keep `POST /messages/repeat` response time bounded and predictable at high counts.
- Avoid request-time coupling to worker wake-up/activation.
- Maintain end-to-end delivery/lifecycle correctness.

### 4.2 Secondary goals

- Reduce noisy polling/load pressure from drain checks.
- Improve operability: clearer metrics for API enqueue, activation, worker handling, and persistence list/get/put timing.

## 5) Optimization plan (ordered)

## 5.1 Phase A - Decouple submit from activation (highest impact)

### A1. Make activation asynchronous from API request path

- Keep enqueueing as the critical path.
- Move worker activation to best-effort background task (or enqueue a wake signal/event).
- Return 200 once enqueue contract is satisfied, with activation failures logged/metriced but non-blocking for response.

### A2. Bound per-request sync work

- Ensure `/messages/repeat` does not block on multi-round activation fanout.
- If needed, cap synchronous activation attempts to a tiny constant and defer the rest.

### A3. Preserve safety and observability

- Add explicit metric counters:
  - enqueue_count / enqueue_latency
  - activation_attempts / activation_failures
  - submit_request_latency

## 5.2 Phase B - Worker activation efficiency

### B1. Reduce activation call cost

- Avoid expensive repeated activations for already-awake workers.
- Coalesce activation requests when large batches are submitted close together.

### B2. Tune worker-side concurrency intentionally

- Reassess `INSPECTIO_WORKER_MAX_PARALLEL_HANDLES` and shard activation batch size based on measured CPU/memory and latency.

## 5.3 Phase C - Persistence and drain-path pressure

### C1. Keep probe hardening (already applied)

- Persist tuned readiness/liveness probe settings in deployment manifests.

### C2. Reduce drain poll aggressiveness

- For large remote runs, use higher `--drain-poll-sec` defaults to reduce list-prefix pressure.
- Consider a cheaper pending-count signal to avoid hot-loop prefix scans.

## 5.4 Phase D - Edge/network timeout consistency

### D1. Keep proxy timeout tuning

- Preserve nginx proxy timeout increases for `/messages` and `/healthz`.

### D2. Verify AWS LB idle timeout policy

- Ensure external load balancer timeout is aligned with intended request model.
- Even with timeout increase, prefer architecture that does not rely on very long synchronous API requests.

## 6) Validation and acceptance criteria

## 6.1 Functional

- Integrity checks pass for smoke and scaled runs after clean-state reset.
- No lifecycle regressions (pending/success/failed invariants preserved).

## 6.2 Performance

- `POST /messages/repeat` high-count requests return within target SLO (to be set; recommended <10s for 10k by decoupling activation).
- 10k batch submission no longer exhibits ~60s client disconnect behavior.
- End-to-end drain completes without persistence restarts.

## 6.3 Reliability

- Persistence restart count remains stable (no probe-induced restarts during load).
- API activation timeout warnings reduce materially after decoupling/coalescing.

## 7) Test plan

1. **Smoke**
   - `--aws --smoke` on clean state.
2. **Step-load**
   - 2k, 5k, 8k, 10k single-batch runs with clean state each run.
3. **Target profile**
   - 10k/20k/30k with tuned drain poll and increased timeouts.
4. **Regression checks**
   - Existing integrity and lifecycle-focused tests.
5. **Operational checks**
   - Confirm pods remain healthy; no probe-related restart loops.

## 8) Risks and mitigations

- **Risk:** Asynchronous activation could delay first processing wave.
  - **Mitigation:** keep a minimal immediate wake signal and monitor wake latency metric.
- **Risk:** Reduced polling frequency slows perceived completion.
  - **Mitigation:** tune for production-like load; separate observability endpoint for pending counts.
- **Risk:** Large request payload still heavy in one call.
  - **Mitigation:** encourage/auto-chunking at client and server boundaries.

## 9) Immediate next implementation tasks

1. Refactor API repeat flow to return after enqueue and make activation non-blocking.
2. Add explicit metrics/log fields for activation queue and failures.
3. Update load script defaults for remote large runs (`drain-poll-sec` guidance).
4. Re-run 10k/20k/30k and capture before/after comparison table.

## 10) Execution roadmap (implementation-ready)

### 10.1 PR-1: Submit-path decoupling and instrumentation (current target)

- [ ] Keep `POST /messages` and `POST /messages/repeat` request critical path limited to enqueue durability.
- [ ] Ensure worker activation remains background-only and non-blocking for API response.
- [ ] Add explicit performance log lines for:
  - enqueue latency and enqueue batch size;
  - activation scheduling counts;
  - activation failure counts in batch wake path.
- [ ] Add/extend unit tests for repeat-submit batching and activation scheduling behavior.
- [ ] Validate with smoke + 2k + 5k + 8k + 10k runs and capture request-latency deltas.

### 10.2 PR-2: Activation efficiency and coalescing

- [ ] Reduce duplicate activations for already targeted workers.
- [ ] Coalesce frequent adjacent activation requests into bounded batches.
- [ ] Add wake-latency metric and worker-target cardinality metric.

### 10.3 PR-3: Drain and persistence pressure reduction

- [ ] Raise default remote `drain-poll-sec` for large runs.
- [ ] Add optional cheap pending-count path to avoid hot-loop list-prefix scans.
- [ ] Verify persistence pod stability under 10k/20k/30k step load.

### 10.4 PR-4: Infra timeout policy hardening

- [ ] Verify and persist nginx + AWS LB timeout alignment.
- [ ] Confirm long timeout paths are no longer required for normal high-volume submit.

## 11) Definition of done (per branch)

- [ ] No functional regression in integrity/lifecycle checks.
- [ ] 10k single submit no longer exhibits ~60s client disconnect pattern.
- [ ] Submit latency distribution materially improved (p50/p95 captured before/after).
- [ ] Persistence remains healthy without probe-induced restart loop.
